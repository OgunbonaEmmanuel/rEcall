"""CLIP's paired encoders. Never compare these 512-D vectors with MiniLM."""
import json
import threading
from importlib.metadata import version
import numpy as np
from PIL import Image, ImageOps
from .config import MODELS, MAX_PIXELS

TEXT_MODEL = 'Qdrant/clip-ViT-B-32-text'
IMAGE_MODEL = 'Qdrant/clip-ViT-B-32-vision'
_text = None
_image = None
_lock = threading.Lock()

def manifest():
    path = MODELS / 'visual-manifest.json'
    if not path.is_file():
        raise RuntimeError('Visual model missing. Run .venv/Scripts/python -m scripts.setup_visual, restart, then reindex images.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if data['fastembed'] != version('fastembed') or data['text_model'] != TEXT_MODEL or data['image_model'] != IMAGE_MODEL:
        raise RuntimeError('Visual model version changed. Run visual setup and explicitly reindex images.')
    for item in data['files']:
        p = MODELS / 'visual' / item['path']
        if not p.is_file() or p.stat().st_size != item['bytes']:
            raise RuntimeError('Visual model cache incomplete. Run visual setup, then retry visual indexing.')
    return data

def model_id():
    return manifest()['fingerprint']

def normalize(vector):
    v = np.asarray(vector, dtype=np.float32)
    if v.shape != (512,) or not np.isfinite(v).all():
        raise ValueError('Invalid visual vector; retry after model setup.')
    return v / max(float(np.linalg.norm(v)), 1e-12)

def text_vector(query):
    global _text
    with _lock:
        manifest()
        if _text is None:
            from fastembed import TextEmbedding
            _text = TextEmbedding(TEXT_MODEL, cache_dir=str(MODELS/'visual'), local_files_only=True,
                                  threads=2, providers=['CPUExecutionProvider'])
        return normalize(next(_text.embed([query])))

def image_vector(path):
    global _image
    with _lock:
        manifest()
        with Image.open(path) as source:
            if source.width * source.height > MAX_PIXELS:
                raise ValueError('Image exceeds 25 megapixels. Resize before uploading.')
            image = ImageOps.exif_transpose(source).convert('RGB')
        if _image is None:
            from fastembed import ImageEmbedding
            _image = ImageEmbedding(IMAGE_MODEL, cache_dir=str(MODELS/'visual'), local_files_only=True,
                                   threads=2, providers=['CPUExecutionProvider'])
        return normalize(next(_image.embed([image])))
