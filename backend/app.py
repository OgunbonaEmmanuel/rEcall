import asyncio
import os
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit
from typing import Literal
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from filelock import FileLock
from .config import DATA, ROOT, MAX_BYTES, prepare
from . import storage
from .embeddings import model_id
from .processing import Processor, mutation_lock
from .retrieval import search

os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
processor = Processor()

@asynccontextmanager
async def lifespan(app):
    global processor
    prepare()
    with FileLock(str(DATA / 'server.lock'), timeout=0):
        storage.init()
        # Keep existing indexes. Queries validate model identities; reindexing is explicit.
        processor = Processor()
        processor.start()
        try: yield
        finally: processor.close()

app = FastAPI(title='Recall local', lifespan=lifespan, docs_url=None, redoc_url=None)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=['localhost', '127.0.0.1', 'testserver'])

class RequestTooLarge(Exception):
    pass

class BodyLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        limit = 10 * MAX_BYTES + 1024 * 1024
        headers = dict(scope['headers'])
        try:
            declared = int(headers.get(b'content-length', b'0'))
        except ValueError:
            declared = limit + 1
        if declared > limit:
            return await JSONResponse({'detail': 'Upload batch exceeds 200 MiB. Use a smaller batch.'}, status_code=413)(scope, receive, send)
        consumed = 0
        async def limited_receive():
            nonlocal consumed
            message = await receive()
            consumed += len(message.get('body', b''))
            if consumed > limit:
                raise RequestTooLarge()
            return message
        try:
            await self.app(scope, limited_receive, send)
        except RequestTooLarge:
            await JSONResponse({'detail': 'Upload batch exceeds 200 MiB.'}, status_code=413)(scope, receive, send)

app.add_middleware(BodyLimit)

@app.middleware('http')
async def local_guard(request, call_next):
    if request.method in {'POST', 'PUT', 'DELETE', 'PATCH'}:
        if request.headers.get('x-recall-client') != 'local':
            return JSONResponse({'detail': 'Local client header required.'}, status_code=403)
        origin = request.headers.get('origin')
        if origin and urlsplit(origin).netloc != request.headers.get('host'):
            return JSONResponse({'detail': 'Only same-origin local requests are allowed.'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Content-Security-Policy'] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'self'"
    return response

def require_file(file_id):
    # Strict generated IDs prevent traversal on every original/preview route.
    import re
    if not re.fullmatch(r'[0-9a-f]{32}', file_id):
        raise HTTPException(404, 'File not found.')
    file = storage.get_file(file_id)
    if not file:
        raise HTTPException(404, 'File not found.')
    return file

@app.get('/api/health')
def health():
    try:
        identity, error = model_id(), None
    except Exception as exc:
        identity, error = None, str(exc)
    from . import visual
    try: visual_identity,visual_error=visual.model_id(),None
    except Exception as exc: visual_identity,visual_error=None,str(exc)
    return {'local': True, 'model': identity, 'model_error': error,'visual_model':visual_identity,'visual_error':visual_error}

@app.get('/api/files')
def files():
    result = storage.list_files()
    with storage.db() as con:
        snippets = {row['file_id']: row['text'] for row in con.execute('SELECT file_id,text FROM chunks WHERE id IN (SELECT MIN(id) FROM chunks GROUP BY file_id)')}
    for file in result:
        file['text'] = snippets.get(file['id'], '')
    return result

@app.post('/api/files')
async def upload(request: Request):
    results = []
    async with request.form(max_files=10, max_fields=0, max_part_size=MAX_BYTES) as form:
        uploads = form.getlist('files')
        if not uploads:
            raise HTTPException(400, 'Choose at least one file.')
        for file in uploads:
            if not hasattr(file, 'read'):
                raise HTTPException(400, 'Expected file uploads.')
            content = await file.read(MAX_BYTES + 1)
            try:
                result = await asyncio.to_thread(storage.ingest, file.filename, content)
                results.append(result)
            except ValueError as exc:
                results.append({'name': file.filename, 'error': str(exc)})
    return {'files': results}

@app.get('/api/search')
def find(q: str = Query(min_length=1, max_length=300), mode: Literal['all','text','visual']='all'):
    return search(q,mode)

@app.get('/api/files/{file_id}')
def detail(file_id: str):
    file = require_file(file_id)
    with storage.db() as con:
        chunks = con.execute('SELECT * FROM chunks WHERE file_id=? ORDER BY page,id', (file_id,)).fetchall()
    return {**file, 'chunks': [storage.serialize_chunk(c) for c in chunks]}

@app.get('/api/files/{file_id}/preview/{page}')
def preview(file_id: str, page: int):
    require_file(file_id)
    if page < 1 or page > 20:
        raise HTTPException(404, 'Page not found.')
    path = DATA / 'previews' / file_id / f'{page}.jpg'
    if not path.is_file():
        raise HTTPException(404, 'Preview is not ready.')
    return FileResponse(path, media_type='image/jpeg')

@app.get('/api/files/{file_id}/original')
def original(file_id: str):
    file = require_file(file_id)
    # Sanitize only the download name, retaining the upload name in metadata.
    safe = Path(file['name'].replace('\\', '/')).name
    import re
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', safe).strip('. ') or f"document.{file['kind']}"
    return FileResponse(DATA / 'originals' / file_id, filename=safe, media_type='application/octet-stream')

@app.post('/api/files/{file_id}/retry')
def retry(file_id: str):
    require_file(file_id)
    if not processor.retry(file_id):
        raise HTTPException(409, 'No failed capability to retry, or processing is already queued.')
    return {'status': 'queued'}

@app.post('/api/files/{file_id}/reindex')
def reindex(file_id: str, scope: Literal['all','text','visual']='all'):
    require_file(file_id)
    if not processor.retry(file_id,scope):
        raise HTTPException(409,'Already queued, or this file does not support the selected capability.')
    return {'status':'queued','scope':scope}

@app.post('/api/files/{file_id}/cancel')
def cancel(file_id: str):
    require_file(file_id)
    if not processor.cancel(file_id): raise HTTPException(409,'No pending job to cancel.')
    return {'cancelled':True}

@app.delete('/api/files/{file_id}')
def delete(file_id: str):
    require_file(file_id)
    processor.delete(file_id)
    return {'deleted': True}

@app.post('/api/demo')
def demo():
    from scripts.fixtures import generate
    paths = generate()
    return {'files': [storage.ingest(path.name, path.read_bytes(), demo=True) for path in paths]}

if (ROOT / 'dist').exists():
    app.mount('/', StaticFiles(directory=ROOT / 'dist', html=True), name='frontend')
