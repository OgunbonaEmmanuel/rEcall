import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = Path(os.environ.get('RECALL_DATA', ROOT / '.recall')).resolve()
MODELS = Path(os.environ.get('RECALL_MODELS', ROOT / '.models')).resolve()
MODEL_NAME = 'sentence-transformers/all-MiniLM-L6-v2'
MAX_BYTES = 20 * 1024 * 1024
MAX_PAGES = 20
MAX_PIXELS = 25_000_000
MAX_CHUNKS = 500
TIMEOUT = int(os.environ.get('RECALL_PROCESS_TIMEOUT', '120'))

def prepare():
    for path in [DATA, DATA / 'originals', DATA / 'previews', DATA / 'work']:
        path.mkdir(parents=True, exist_ok=True)
