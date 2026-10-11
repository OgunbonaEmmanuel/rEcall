"""One bounded job, independently staged text and visual capabilities."""
import json
import sys
from pathlib import Path
from filelock import FileLock
from .config import DATA
from .job_files import guard_parent

def atomic_json(path,value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value),encoding='utf-8')
    temporary.replace(path)

def main():
    path,kind,output,*options=sys.argv[1:]
    scope=options[0] if options else 'all'
    out=Path(output)
    if len(options)>=3:
        guard_parent(int(options[1]),float(options[2]))
        if not out.is_dir(): return
    else: out.mkdir(parents=True,exist_ok=True)
    (DATA/'locks').mkdir(parents=True,exist_ok=True)
    with FileLock(str(DATA/'locks'/f'{out.name}.lock')):
        from .extraction import extract,save_preview
        from .embeddings import embed,model_id
        from . import visual
        from PIL import Image,ImageOps
        if scope in ('all','text'):
            try:
                data=extract(Path(path),kind,out)
                data.update(state='ready',model=None,error=None)
                try:
                    identity=model_id()
                    if data['chunks']:
                        for chunk,vector in zip(data['chunks'],embed([c['text'] for c in data['chunks']])):
                            chunk['vector']=vector.tolist()
                    data['model']=identity
                except Exception as exc:
                    data.update(state='partial' if data['chunks'] else 'failed',error=f'Text embeddings unavailable: {str(exc)[:400]}')
                    for chunk in data['chunks']: chunk['vector']=[]
            except Exception as exc:
                data={'state':'failed','error':f'{type(exc).__name__}: {str(exc)[:400]} Export a fresh copy or check setup, then retry.'}
            atomic_json(out/'text.json',data)
        if kind in ('png','jpeg') and scope in ('all','visual'):
            try:
                with Image.open(path) as image:
                    from .config import MAX_PIXELS
                    if image.width*image.height>MAX_PIXELS: raise ValueError('Image exceeds 25 megapixels. Resize it.')
                    save_preview(ImageOps.exif_transpose(image),out,1)
                identity=visual.model_id()
                data={'state':'ready','model':identity,'vector':visual.image_vector(path).tolist(),'error':None}
            except Exception as exc:
                data={'state':'failed','error':f'Visual indexing unavailable: {str(exc)[:400]}'}
            atomic_json(out/'visual.json',data)

if __name__=='__main__': main()
