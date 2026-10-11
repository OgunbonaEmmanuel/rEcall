import json
from pathlib import Path
import pytest
from backend import storage, processing, retrieval
from backend.config import MAX_BYTES

@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'DATA', tmp_path)
    monkeypatch.setattr(processing, 'DATA', tmp_path)
    for name in ['originals', 'previews', 'work']:
        (tmp_path / name).mkdir()
    storage.init()
    return tmp_path

def test_content_dedup_and_safe_names(data):
    content = b'%PDF-1.7 synthetic bytes'
    first = storage.ingest('../../outside.pdf', content)
    second = storage.ingest('another.pdf', content)
    assert second['duplicate'] and first['id'] == second['id']
    assert storage.get_file(first['id'])['name'] == '../../outside.pdf'
    assert [p.name for p in (data / 'originals').iterdir()] == [first['id']]
    assert not (data.parent / 'outside.pdf').exists()
    assert storage.list_files()[0]['demo'] is False
    storage.ingest('synthetic.pdf', content, demo=True)
    assert storage.list_files()[0]['demo'] is True
    long_name = 'x' * 248 + '.pdf'
    long_file = storage.ingest(long_name, b'%PDF-1.7 long name')
    assert storage.get_file(long_file['id'])['name'] == long_name

def test_upload_limits_and_signatures(data):
    with pytest.raises(ValueError, match='empty'):
        storage.ingest('empty.pdf', b'')
    with pytest.raises(ValueError, match='Unsupported'):
        storage.ingest('fake.png', b'<script>alert(1)</script>')
    with pytest.raises(ValueError, match='20 MiB'):
        storage.ingest('large.pdf', b'%PDF-' + b'x' * MAX_BYTES)

def test_delete_cascades_text_and_assets(data):
    import numpy as np
    file_id = storage.ingest('sample.pdf', b'%PDF-1.7 deletion')['id']
    for folder in ['previews', 'work']:
        (data / folder / file_id).mkdir()
        (data / folder / file_id / '1.jpg').write_bytes(b'preview')
    with storage.db() as con:
        con.execute('INSERT INTO chunks(file_id,page,text,boxes,method,vector,model) VALUES(?,?,?,?,?,?,?)',
                    (file_id, 1, 'secretword', '[]', 'PDF text', np.zeros(384,dtype=np.float32).tobytes(), 'test'))
    processing.Processor().delete(file_id)
    assert storage.get_file(file_id) is None
    assert not (data / 'originals' / file_id).exists()
    assert not (data / 'previews' / file_id).exists()
    assert not (data / 'work' / file_id).exists()
    with storage.db() as con:
        assert con.execute('SELECT COUNT(*) FROM chunks').fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM chunk_fts WHERE chunk_fts MATCH 'secretword'").fetchone()[0] == 0

def test_recovery_and_retry(data):
    file_id = storage.ingest('x.pdf', b'%PDF-1.7 retry')['id']
    with storage.db() as con:
        con.execute("UPDATE files SET status='processing' WHERE id=?", (file_id,))
    storage.init()
    assert storage.get_file(file_id)['status'] == 'queued'
    processor = processing.Processor()
    assert not processor.retry(file_id)
    with storage.db() as con:
        con.execute("UPDATE files SET status='failed',error='test failure' WHERE id=?", (file_id,))
    assert processor.retry(file_id)
    assert storage.get_file(file_id)['error'] is None

def test_keyword_fallback_and_numeric_precision(data, monkeypatch):
    import numpy as np
    def unavailable():
        raise RuntimeError('Local models unavailable')
    monkeypatch.setattr(retrieval, 'model_id', unavailable)
    file_id = storage.ingest('x.pdf', b'%PDF-1.7 searchable')['id']
    with storage.db() as con:
        con.execute("UPDATE files SET status='ready' WHERE id=?", (file_id,))
        con.execute('INSERT INTO chunks(file_id,page,text,boxes,method,vector,model) VALUES(?,?,?,?,?,?,?)',
            (file_id,2,'Headphone receipt $89.99',json.dumps([{'text':'Headphone receipt $89.99','box':[0,0,1,1]}]),'PDF text',np.zeros(384,dtype=np.float32).tobytes(),'test'))
    result = retrieval.search('89.99')
    assert result['warning'] and result['results'][0]['page'] == 2
    assert retrieval.search('89.98')['results'] == []
    assert retrieval.search('"headphone receipt"')['results'][0]['match'] == 'Exact phrase'
    assert retrieval.search('" OR * (')['results'] == []

def test_scanned_and_pdf_page_limits(tmp_path):
    import pymupdf
    from backend.extraction import extract
    pdf = tmp_path / 'too_many.pdf'
    with pymupdf.open() as doc:
        for _ in range(21): doc.new_page()
        doc.save(pdf)
    with pytest.raises(ValueError, match='1–20'):
        extract(pdf, 'pdf', tmp_path / 'out')

def test_timeout_kills_worker(data, monkeypatch):
    import subprocess
    file_id = storage.ingest('slow.pdf', b'%PDF-1.7 slow')['id']
    class SlowProcess:
        killed = False
        def __init__(self, *args, **kwargs): pass
        def wait(self, timeout=None):
            if not self.killed: raise subprocess.TimeoutExpired('worker', timeout)
            return -1
        def kill(self): self.killed = True
    monkeypatch.setattr(processing.subprocess, 'Popen', SlowProcess)
    processing.Processor().process_one(storage.get_file(file_id))
    file = storage.get_file(file_id)
    assert file['status'] == 'failed' and 'exceeded' in file['error']
    assert not (data / 'work' / file_id).exists()
