import hashlib
import json
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager
from .config import DATA, MAX_BYTES, prepare

@contextmanager
def db():
    con = sqlite3.connect(DATA / 'recall.sqlite3', timeout=15)
    con.row_factory = sqlite3.Row
    con.execute('PRAGMA foreign_keys=ON')
    con.execute('PRAGMA secure_delete=ON')
    try:
        with con:
            yield con
    finally:
        con.close()

def init():
    prepare()
    with db() as con:
        con.executescript('''
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS files (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, hash TEXT UNIQUE NOT NULL,
          kind TEXT NOT NULL, size INTEGER NOT NULL, status TEXT NOT NULL,
          created REAL NOT NULL, pages INTEGER DEFAULT 0, error TEXT,
          warning TEXT, seconds REAL, model TEXT, demo INTEGER DEFAULT 0);
        CREATE TABLE IF NOT EXISTS chunks (
          id INTEGER PRIMARY KEY, file_id TEXT NOT NULL REFERENCES files(id) ON DELETE CASCADE,
          page INTEGER NOT NULL, text TEXT NOT NULL, boxes TEXT NOT NULL,
          method TEXT NOT NULL, vector BLOB NOT NULL, model TEXT NOT NULL);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(text, content='chunks', content_rowid='id');
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
          INSERT INTO chunk_fts(rowid,text) VALUES (new.id,new.text); END;
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
          INSERT INTO chunk_fts(chunk_fts,rowid,text) VALUES('delete',old.id,old.text); END;
        ''')
        con.execute('BEGIN IMMEDIATE')
        # Additive, transactional migration: no replacement tables, originals or indexes.
        columns = {r['name'] for r in con.execute('PRAGMA table_info(files)')}
        additions = {'text_status':"TEXT NOT NULL DEFAULT 'pending'", 'visual_status':"TEXT NOT NULL DEFAULT 'not_applicable'",
                     'text_error':'TEXT', 'visual_error':'TEXT', 'queue_scope':"TEXT NOT NULL DEFAULT 'all'", 'job_token':'TEXT'}
        for name, definition in additions.items():
            if name not in columns:
                con.execute(f'ALTER TABLE files ADD COLUMN {name} {definition}')
        if 'text_status' not in columns:
            con.execute("UPDATE files SET text_status=CASE WHEN status='ready' THEN 'ready' WHEN status='failed' THEN 'failed' ELSE 'pending' END")
            con.execute("UPDATE files SET visual_status='not_indexed' WHERE kind IN ('png','jpeg')")
        chunk_columns = {r['name'] for r in con.execute('PRAGMA table_info(chunks)')}
        if 'reference' not in chunk_columns:
            con.execute('ALTER TABLE chunks ADD COLUMN reference TEXT')
        con.execute('CREATE TABLE IF NOT EXISTS visual_vectors (file_id TEXT PRIMARY KEY REFERENCES files(id) ON DELETE CASCADE, vector BLOB NOT NULL, model TEXT NOT NULL)')
        con.execute('PRAGMA user_version=2')
        con.execute("UPDATE files SET status='queued', error=NULL WHERE status='processing'")

def get_file(file_id):
    with db() as con:
        row = con.execute('SELECT * FROM files WHERE id=?', (file_id,)).fetchone()
    return {**dict(row), 'demo': bool(row['demo'])} if row else None

def list_files():
    with db() as con:
        return [{**dict(row), 'demo': bool(row['demo'])} for row in con.execute('SELECT * FROM files ORDER BY created DESC')]

def ingest(name, content, demo=False):
    # Names are display metadata only. Filesystem paths always use generated UUIDs.
    name = re.sub(r'[\x00-\x1f\x7f]', '', name or 'Untitled') or 'Untitled'
    if not content:
        raise ValueError('This file is empty. Choose a PNG, JPEG, PDF or DOCX with content.')
    if len(content) > MAX_BYTES:
        raise ValueError('This file exceeds 20 MiB. Export a smaller file and upload it again.')
    if name.lower().endswith(('.doc','.docm')) or content.startswith(b'\xd0\xcf\x11\xe0'):
        raise ValueError('DOC, DOCM and encrypted Office files are unsupported. Save an unlocked, macro-free DOCX.')
    if content.startswith(b'PK') or name.lower().endswith('.docx'):
        from .docx import validate
        validate(content)
        kind = 'docx'
    elif content.startswith(b'%PDF-'):
        kind = 'pdf'
    elif content.startswith(b'\x89PNG\r\n\x1a\n'):
        kind = 'png'
    elif content.startswith(b'\xff\xd8\xff'):
        kind = 'jpeg'
    else:
        raise ValueError('Unsupported file content. Choose an actual PNG, JPEG, PDF or DOCX.')
    digest = hashlib.sha256(content).hexdigest()
    with db() as con:
        existing = con.execute('SELECT id FROM files WHERE hash=?', (digest,)).fetchone()
        if existing:
            if demo:
                con.execute('UPDATE files SET demo=1 WHERE id=?', (existing['id'],))
            return {'id': existing['id'], 'name': name, 'duplicate': True}
        file_id = uuid.uuid4().hex
        original = DATA / 'originals' / file_id
        original.write_bytes(content)
        try:
            con.execute('INSERT INTO files(id,name,hash,kind,size,status,created,demo) VALUES(?,?,?,?,?,?,?,?)',
                        (file_id, name, digest, kind, len(content), 'queued', time.time(), int(demo)))
            if kind in ('png','jpeg'):
                con.execute("UPDATE files SET visual_status='pending' WHERE id=?",(file_id,))
        except sqlite3.IntegrityError:
            original.unlink(missing_ok=True)
            existing = con.execute('SELECT id FROM files WHERE hash=?', (digest,)).fetchone()
            if existing:
                if demo:
                    con.execute('UPDATE files SET demo=1 WHERE id=?', (existing['id'],))
                return {'id': existing['id'], 'name': name, 'duplicate': True}
            raise
        except Exception:
            original.unlink(missing_ok=True)
            raise
    return {'id': file_id, 'name': name, 'duplicate': False}

def serialize_chunk(row):
    return {'page': row['page'] or None, 'text': row['text'], 'boxes': json.loads(row['boxes']), 'method': row['method'],
            'reference': row['reference'] if 'reference' in row.keys() else None}
