"""Explicit download of paired CLIP weights; no user files or queries are read."""
import hashlib
import json
from importlib.metadata import version
from backend.config import MODELS
from backend.visual import TEXT_MODEL, IMAGE_MODEL

def main():
    from fastembed import TextEmbedding, ImageEmbedding
    cache = MODELS / 'visual'
    cache.mkdir(parents=True, exist_ok=True)
    print('Downloading public CLIP encoders (~600 MB). No user files are uploaded.', flush=True)
    TextEmbedding(TEXT_MODEL, cache_dir=str(cache), threads=2, providers=['CPUExecutionProvider'])
    ImageEmbedding(IMAGE_MODEL, cache_dir=str(cache), threads=2, providers=['CPUExecutionProvider'])
    files = []
    for path in sorted(cache.rglob('*')):
        if path.is_file() and '.locks' not in str(path) and 'snapshots' in path.parts:
            with path.open('rb') as handle:
                sha = hashlib.file_digest(handle, 'sha256').hexdigest()
            files.append({'path': path.relative_to(cache).as_posix(), 'bytes': path.stat().st_size, 'sha256': sha})
    if not files:
        raise RuntimeError('Downloaded cache has no snapshot files.')
    identity = hashlib.sha256(json.dumps(files,sort_keys=True).encode()).hexdigest()
    data = {'text_model': TEXT_MODEL, 'image_model': IMAGE_MODEL, 'fastembed': version('fastembed'),
            'license': 'MIT', 'dimension':512, 'fingerprint':'clip-ViT-B-32:'+version('fastembed')+':'+identity,
            'files': files, 'download_bytes':sum(f['bytes'] for f in files)}
    (MODELS/'visual-manifest.json').write_text(json.dumps(data,indent=2), encoding='utf-8')
    print(f"Visual setup complete: {data['download_bytes']/1024**2:.1f} MiB.",flush=True)

if __name__ == '__main__': main()
