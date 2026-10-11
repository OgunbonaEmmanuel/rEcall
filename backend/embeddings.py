import hashlib
import json
import threading
from importlib.metadata import version
import numpy as np
from .config import MODELS, MODEL_NAME

_model = None
_lock = threading.Lock()

def manifest():
    path = MODELS / 'manifest.json'
    if not path.exists():
        raise RuntimeError('Local models are missing. Run .venv/Scripts/python -m scripts.setup_models, then retry.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['name'] != MODEL_NAME or data['fastembed'] != version('fastembed'):
        raise RuntimeError('Model version changed. Run model setup again, restart Recall, and retry affected files.')
    return data

def model_id():
    return manifest()['fingerprint']

def embed(texts):
    global _model
    with _lock:
        manifest()
        if _model is None:
            from fastembed import TextEmbedding
            _model = TextEmbedding(MODEL_NAME, cache_dir=str(MODELS / 'embedding'),
                                   local_files_only=True, threads=2, providers=['CPUExecutionProvider'])
        vectors = np.asarray(list(_model.embed(texts)), dtype=np.float32)
        norms = np.linalg.norm(vectors, axis=1, keepdims=True)
        return vectors / np.maximum(norms, 1e-12)

def fingerprint(paths):
    digest = hashlib.sha256()
    for path in sorted(paths):
        with path.open('rb') as stream:
            while block := stream.read(1024 * 1024):
                digest.update(block)
    return digest.hexdigest()
