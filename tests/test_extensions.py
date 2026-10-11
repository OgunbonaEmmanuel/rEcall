import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path
import numpy as np
import psutil
import pytest
from backend import docx, storage, processing, job_files
from scripts.extension_fixtures import docx_bytes, paragraph
from tests.test_core import data

def test_docx_order_sources_and_limits(tmp_path):
    path=tmp_path/'input.docx'
    body=paragraph('Budget',True)+paragraph('Nora Bennett')+'<w:tbl><w:tr><w:tc>'+paragraph('$127.45')+'</w:tc></w:tr></w:tbl>'+paragraph('After table')
    path.write_bytes(docx_bytes(body))
    result=docx.extract(path)
    assert [c['text'] for c in result['chunks']]==['Budget','Nora Bennett','$127.45','After table']
    assert result['chunks'][2]['reference']=='Table 1, row 1, cell 1 · Budget'
    assert all(c['page']==0 and not c['boxes'] for c in result['chunks'])
    path.write_bytes(docx_bytes(paragraph('X'*(docx.MAX_TEXT+1))))
    with pytest.raises(ValueError,match='200,000'): docx.extract(path)

def test_docx_rejects_unsafe_packages(data):
    with pytest.raises(ValueError,match='DOC, DOCM'): storage.ingest('macro.docm',docx_bytes(paragraph('hello')))
    with pytest.raises(ValueError,match='Malformed'): storage.ingest('broken.docx',b'PKmalformed')
    for member,content,match in [('../escape','x','Unsafe'),('word/vbaProject.bin','x','Macro'),('bomb',b'x'*(docx.MAX_EXPANDED+1),'50 MiB')]:
        stream=io.BytesIO(docx_bytes(paragraph('hello')))
        with zipfile.ZipFile(stream,'a',zipfile.ZIP_DEFLATED) as z: z.writestr(member,content)
        with pytest.raises(ValueError,match=match): docx.validate(stream.getvalue())
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w') as z:
        for i in range(1001): z.writestr(str(i),'')
    with pytest.raises(ValueError,match='1,000'): docx.validate(stream.getvalue())
    hostile=docx_bytes(paragraph('safe')).replace(b'nonexistent',b'')
    stream=io.BytesIO(hostile)
    with zipfile.ZipFile(stream,'a') as z: z.writestr('word/evil.xml','<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>')
    # Unsupported parts are never parsed or executed; archive is bounded only.
    docx.validate(stream.getvalue())

def test_v1_migration_preserves_existing_data(tmp_path,monkeypatch):
    monkeypatch.setattr(storage,'DATA',tmp_path)
    con=sqlite3.connect(tmp_path/'recall.sqlite3')
    con.executescript("CREATE TABLE files(id TEXT PRIMARY KEY,name TEXT,hash TEXT UNIQUE,kind TEXT,size INTEGER,status TEXT,created REAL,pages INTEGER,error TEXT,warning TEXT,seconds REAL,model TEXT,demo INTEGER); CREATE TABLE chunks(id INTEGER PRIMARY KEY,file_id TEXT REFERENCES files(id) ON DELETE CASCADE,page INTEGER,text TEXT,boxes TEXT,method TEXT,vector BLOB,model TEXT); INSERT INTO files VALUES('old','photo.jpg','hash','jpeg',3,'ready',1,1,NULL,NULL,2,'old-model',0); INSERT INTO chunks VALUES(1,'old',1,'keep this text','[]','OCR',X'00000000','old-model');")
    con.commit();con.close()
    storage.init();storage.init()
    file=storage.get_file('old')
    assert file['status']=='ready' and file['visual_status']=='not_indexed'
    with storage.db() as con:
        assert con.execute('SELECT text FROM chunks').fetchone()[0]=='keep this text'
        assert con.execute('PRAGMA user_version').fetchone()[0]==2

def test_partial_failure_keeps_other_index(data):
    file_id=storage.ingest('photo.png',b'\x89PNG\r\n\x1a\nfixture')['id']
    out=data/'work'/'staged';out.mkdir()
    (out/'text.json').write_text(json.dumps({'state':'ready','chunks':[{'page':1,'text':'Receipt $89.99','boxes':[],'method':'OCR','vector':[1.,0.]}],'model':'mini','pages':1,'warning':None,'error':None}))
    (out/'visual.json').write_text(json.dumps({'state':'failed','error':'Visual model missing'}))
    processor=processing.Processor()
    processor.commit(storage.get_file(file_id),out,'all',None,1)
    file=storage.get_file(file_id)
    assert file['status']=='ready' and file['text_status']=='ready' and file['visual_status']=='failed'
    assert processor.retry(file_id)
    with storage.db() as con: assert con.execute('SELECT count(*) FROM chunks').fetchone()[0]==1
    (out/'visual.json').write_text(json.dumps({'state':'ready','vector':[1.]+[0.]*511,'model':'clip','error':None}))
    processor.commit(storage.get_file(file_id),out,'visual',None,1)
    with storage.db() as con:
        assert con.execute('SELECT count(*) FROM chunks').fetchone()[0]==1
        assert con.execute('SELECT count(*) FROM visual_vectors').fetchone()[0]==1
    processor.delete(file_id)
    with storage.db() as con: assert con.execute('SELECT count(*) FROM visual_vectors').fetchone()[0]==0

def test_cleanup_keeps_unknown_and_live_owner(data,monkeypatch):
    unknown=data/'work'/'notes';unknown.mkdir();(unknown/'keep').write_text('not a generated job')
    disposable=data/'work'/('a'*32);disposable.mkdir();(disposable/'text.json').write_text('{}')
    monkeypatch.setattr(job_files,'workers_for',lambda p: [])
    job_files.reconcile(data)
    assert not disposable.exists() and unknown.exists()
    protected=data/'work'/('b'*32);protected.mkdir()
    (protected/'owner.json').write_text(json.dumps({'parent_pid':99999,'parent_created':1}))
    monkeypatch.setattr(job_files,'same_process',lambda *args: object())
    assert not job_files.cleanup_job(protected,data) and protected.exists()

def test_text_embedding_reindex_failure_preserves_working_indexes(data):
    file_id=storage.ingest('photo.png',b'\x89PNG\r\n\x1a\nreindex-fixture')['id']
    out=data/'work'/'staged';out.mkdir()
    chunk={'page':1,'text':'Original receipt','boxes':[],'method':'OCR','vector':[1.,0.]}
    text_result={'state':'ready','chunks':[chunk],'model':'mini','pages':1,'warning':None,'error':None}
    (out/'text.json').write_text(json.dumps(text_result))
    (out/'visual.json').write_text(json.dumps({'state':'ready','vector':[1.]+[0.]*511,'model':'clip','error':None}))
    processor=processing.Processor()
    processor.commit(storage.get_file(file_id),out,'all',None,1)
    text_result.update(state='partial',error='Text model unavailable',model=None)
    text_result['chunks']=[{**chunk,'text':'Replacement OCR','vector':[]}]
    (out/'text.json').write_text(json.dumps(text_result))
    processor.commit(storage.get_file(file_id),out,'text',None,1)
    file=storage.get_file(file_id)
    assert file['status']=='ready' and file['text_status']=='ready' and file['visual_status']=='ready'
    assert file['text_error']=='Text model unavailable'
    with storage.db() as con:
        row=con.execute('SELECT * FROM chunks WHERE file_id=?',(file_id,)).fetchone()
        assert row['text']=='Original receipt' and len(row['vector'])==8
        assert con.execute('SELECT count(*) FROM visual_vectors').fetchone()[0]==1

def test_windows_handle_retry_and_cancel(data,monkeypatch):
    target=data/'work'/('c'*32);target.mkdir()
    original=job_files.shutil.rmtree
    calls=[]
    def flaky(path):
        calls.append(path)
        if len(calls)<3: raise PermissionError('Windows sharing violation')
        original(path)
    monkeypatch.setattr(job_files.shutil,'rmtree',flaky)
    assert job_files.safe_remove(target,data) and len(calls)==3
    file_id=storage.ingest('queued.pdf',b'%PDF-cancel')['id']
    processor=processing.Processor()
    assert processor.cancel(file_id)
    assert storage.get_file(file_id)['status']=='failed'
    assert (data/'originals'/file_id).exists()
    assert processor.retry(file_id)

def test_cleanup_scope_and_old_document_attempts(data,monkeypatch):
    file_id=storage.ingest('queued.pdf',b'%PDF-old-attempts')['id']
    staged=data/'work'/('d'*32);staged.mkdir()
    unknown=data/'work'/'notes';unknown.mkdir()
    for path in (staged,unknown):
        (path/'owner.json').write_text(json.dumps({'file_id':file_id}))
    monkeypatch.setattr(job_files,'workers_for',lambda p: pytest.fail('Must validate path before inspecting workers'))
    with pytest.raises(ValueError): job_files.cleanup_job(data/'originals',data)
    with pytest.raises(ValueError): job_files.cleanup_job(data/'work',data)
    assert (data/'originals'/file_id).exists()
    monkeypatch.setattr(job_files,'workers_for',lambda p: [])
    processing.Processor().delete(file_id)
    assert not staged.exists() and unknown.exists()
    assert not (data/'originals'/file_id).exists()

def test_docx_xml_parts_and_entities_are_bounded():
    stream=io.BytesIO(docx_bytes(paragraph('safe')))
    with zipfile.ZipFile(stream,'a',zipfile.ZIP_DEFLATED) as z:
        z.writestr('word/unused.xml',b'x'*(docx.MAX_XML+1))
    with pytest.raises(ValueError,match='8 MiB'): docx.validate(stream.getvalue())
    original=zipfile.ZipFile(io.BytesIO(docx_bytes(paragraph('safe'))))
    hostile=io.BytesIO()
    with original,zipfile.ZipFile(hostile,'w') as z:
        for name in original.namelist():
            value=original.read(name)
            if name=='word/document.xml':
                value=b'<!DOCTYPE a [<!ENTITY x SYSTEM "file:///etc/passwd">]><a>&x;</a>'
            z.writestr(name,value)
    with pytest.raises(ValueError): docx.validate(hostile.getvalue())
