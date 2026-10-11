"""Extract untrusted documents to text and raster previews; no HTML or PDF execution."""
import re
import warnings
import numpy as np
import pymupdf
from PIL import Image, ImageOps
from .config import MAX_PAGES, MAX_PIXELS, MAX_CHUNKS, MODELS
from .embeddings import manifest

Image.MAX_IMAGE_PIXELS = MAX_PIXELS
warnings.simplefilter('error', Image.DecompressionBombWarning)
_ocr = None

def ocr_engine():
    global _ocr
    if _ocr is None:
        from rapidocr import RapidOCR
        from rapidocr.utils.download_file import DownloadFile
        def no_download(*args, **kwargs):
            raise RuntimeError('OCR model is missing. Run model setup, then retry.')
        # Defense against implicit dictionary/model downloads in the OCR library.
        DownloadFile.run = staticmethod(no_download)
        data = manifest()
        params = {'Global.log_level': 'error', 'EngineConfig.onnxruntime.intra_op_num_threads': 2,
                  'EngineConfig.onnxruntime.inter_op_num_threads': 1}
        for stage, name in data['ocr'].items():
            path = MODELS / 'ocr' / name
            if not path.is_file():
                raise RuntimeError('OCR model is missing. Run model setup, then retry.')
            params[f'{stage}.model_path'] = str(path)
        _ocr = RapidOCR(params=params)
    return _ocr

def readable(text):
    return len(re.findall(r'[A-Za-z0-9]', text)) >= 12

def raster_lines(image):
    result = ocr_engine()(np.asarray(image.convert('RGB')))
    if not result.txts:
        return []
    width, height = image.size
    lines = []
    for text, box, score in zip(result.txts, result.boxes, result.scores):
        if score < 0.5 or not text.strip():
            continue
        box = np.asarray(box)
        lines.append({'text': text.strip(), 'box': [float(box[:, 0].min() / width), float(box[:, 1].min() / height),
                                                   float(box[:, 0].max() / width), float(box[:, 1].max() / height)]})
    return lines

def chunks_from_lines(lines, page, method):
    # <= ~180 tokens per chunk, with overlap so adjacent receipt lines stay together.
    chunks, group, length = [], [], 0
    for line in lines:
        # Also split unusually long PDF spans without losing source coordinates.
        for offset in range(0, len(line['text']), 650):
            part = {**line, 'text': line['text'][offset:offset + 650]}
            if group and length + len(part['text']) > 750:
                chunks.append({'page': page, 'text': '\n'.join(x['text'] for x in group),
                               'boxes': group, 'method': method})
                group = group[-2:] if len(group) > 2 else []
                length = sum(len(x['text']) for x in group)
            group.append(part)
            length += len(part['text']) + 1
    if group:
        chunks.append({'page': page, 'text': '\n'.join(x['text'] for x in group), 'boxes': group, 'method': method})
    return chunks

def save_preview(image, out, page):
    image = image.convert('RGB')
    image.thumbnail((1200, 1600))
    image.save(out / f'{page}.jpg', quality=85)

def extract(path, kind, out):
    out.mkdir(parents=True, exist_ok=True)
    if kind == 'docx':
        from .docx import extract as extract_docx
        return extract_docx(path)
    chunks, unreadable_pages = [], []
    if kind == 'pdf':
        with pymupdf.open(path) as doc:
            if doc.needs_pass:
                raise ValueError('This PDF is password protected. Upload an unlocked copy.')
            if not 1 <= len(doc) <= MAX_PAGES:
                raise ValueError('PDFs must contain 1–20 pages. Split this PDF into smaller files.')
            pages = len(doc)
            for number, page in enumerate(doc, 1):
                # Rotation matrix maps PDF text coordinates into displayed preview coordinates.
                lines = []
                for block in page.get_text('dict', flags=pymupdf.TEXTFLAGS_DICT & ~pymupdf.TEXT_PRESERVE_IMAGES)['blocks']:
                    for line in block.get('lines', []):
                        text = ''.join(s['text'] for s in line['spans']).strip()
                        rect = pymupdf.Rect(line['bbox']) * page.rotation_matrix
                        if text:
                            lines.append({'text': text, 'box': [rect.x0 / page.rect.width, rect.y0 / page.rect.height,
                                                               rect.x1 / page.rect.width, rect.y1 / page.rect.height]})
                scale = min(2, 2200 / max(page.rect.width, page.rect.height))
                pix = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
                method = 'PDF text'
                if not readable(' '.join(line['text'] for line in lines)):
                    lines = raster_lines(image)
                    method = 'OCR'
                save_preview(image, out, number)
                if not readable(' '.join(line['text'] for line in lines)):
                    unreadable_pages.append(number)
                chunks.extend(chunks_from_lines(lines, number, method))
                if len(chunks) > MAX_CHUNKS:
                    raise ValueError('This document has too much text. Split it into smaller files (500 chunks maximum).')
    else:
        with Image.open(path) as original:
            if original.width * original.height > MAX_PIXELS:
                raise ValueError('This image exceeds 25 megapixels. Resize it before uploading.')
            image = ImageOps.exif_transpose(original).convert('RGB')
        image.thumbnail((2200, 2200))
        save_preview(image, out, 1)
        lines = raster_lines(image)
        chunks = chunks_from_lines(lines, 1, 'OCR')
        pages = 1
        if not readable(' '.join(line['text'] for line in lines)):
            unreadable_pages.append(1)
    if len(chunks) > MAX_CHUNKS:
        raise ValueError('Too much text. Split this file into smaller files (500 chunks maximum).')
    warning = None
    if unreadable_pages:
        warning = 'Insufficient readable text on page(s) ' + ', '.join(map(str, unreadable_pages)) + '. Text search is limited; standalone images may still be searchable visually.'
    return {'pages': pages, 'chunks': chunks, 'warning': warning}
