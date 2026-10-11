"""Explicit network-enabled setup; never called by the application."""
import json
import shutil
from pathlib import Path
from importlib.metadata import version
from backend.config import MODELS, MODEL_NAME
from backend.embeddings import fingerprint

def main():
    from fastembed import TextEmbedding
    import rapidocr
    MODELS.mkdir(parents=True, exist_ok=True)
    print('Downloading public embedding model weights. No user files are read or uploaded.', flush=True)
    model = TextEmbedding(MODEL_NAME, cache_dir=str(MODELS / 'embedding'), threads=2,
                          providers=['CPUExecutionProvider'])
    list(model.embed(['Model setup check']))
    ocr_dir = MODELS / 'ocr'
    ocr_dir.mkdir(exist_ok=True)
    bundled = Path(rapidocr.__file__).parent / 'models'
    names = {'Det': 'PP-OCRv6_det_small.onnx', 'Rec': 'PP-OCRv6_rec_small.onnx',
             'Cls': 'ch_ppocr_mobile_v2.0_cls_mobile.onnx'}
    for name in names.values():
        shutil.copyfile(bundled / name, ocr_dir / name)
    paths = [p for p in (MODELS / 'embedding').rglob('*') if p.is_file() and '.locks' not in str(p)]
    data = {'name': MODEL_NAME, 'fastembed': version('fastembed'), 'rapidocr': version('rapidocr'),
            'fingerprint': MODEL_NAME + ':' + version('fastembed') + ':' + fingerprint(paths),
            'ocr': names, 'ocr_sha256': fingerprint(list(ocr_dir.glob('*.onnx')))}
    (MODELS / 'manifest.json').write_text(json.dumps(data, indent=2), encoding='utf-8')
    from backend.extraction import ocr_engine
    ocr_engine()
    print('Local model setup complete. Runtime uses only these cached files.', flush=True)

if __name__ == '__main__':
    main()
