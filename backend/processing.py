"""Persistent queue; independent text/visual commits; recoverable staging."""
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import uuid
import numpy as np
import psutil
from .config import DATA, ROOT, TIMEOUT
from .storage import db, get_file
from .job_files import cleanup_job, reconcile, safe_remove

log = logging.getLogger(__name__)
mutation_lock = threading.RLock()

def remove_tree(path):
    if not safe_remove(path,DATA):
        raise OSError('Files still in use by Windows. Close the viewer and retry.')

class Processor:
    def __init__(self):
        self.stop=threading.Event()
        self.process=None
        self.current_id=None
        self.cancelled=set()
        self.thread=threading.Thread(target=self.run,daemon=True,name='recall-processor')

    def start(self):
        reconcile(DATA)
        self.thread.start()

    def close(self):
        self.stop.set()
        with mutation_lock: self._kill()
        self.thread.join(timeout=20)

    def _kill(self):
        if self.process and self.process.poll() is None:
            self.process.kill()
            self.process.wait(timeout=10)

    def cancel(self,file_id):
        with mutation_lock, db() as con:
            row=con.execute('SELECT status FROM files WHERE id=?',(file_id,)).fetchone()
            if not row or row['status'] not in ('queued','processing'): return False
            self.cancelled.add(file_id)
            if self.current_id==file_id: self._kill()
            available=self._available(con,file_id)
            con.execute("UPDATE files SET status=?,error='Processing cancelled. Retry or reindex to continue.' WHERE id=?",('ready' if available else 'failed',file_id))
            return True

    def delete(self,file_id):
        with mutation_lock:
            self.cancelled.add(file_id)
            if self.current_id==file_id: self._kill()
            file=get_file(file_id)
            # Older deferred attempts may remain after a Windows sharing violation.
            # Delete all staging owned by this document, not only its latest job token.
            for staged in (DATA/'work').iterdir():
                if (not staged.is_dir() or staged.is_symlink() or staged.is_junction()
                        or not re.fullmatch('[0-9a-f]{32}',staged.name)): continue
                try: owner=json.loads((staged/'owner.json').read_text(encoding='utf-8'))
                except (OSError,ValueError): continue
                if isinstance(owner,dict) and owner.get('file_id')==file_id and not cleanup_job(staged,DATA):
                    raise OSError('An earlier processing attempt is still in use. Retry deletion shortly.')
            if file and file.get('job_token'):
                if not cleanup_job(DATA/'work'/file['job_token'],DATA):
                    raise OSError('Temporary files still in use. Retry deletion shortly.')
            if not cleanup_job(DATA/'work'/file_id,DATA):
                raise OSError('Legacy processing files still in use. Retry deletion shortly.')
            (DATA/'originals'/file_id).unlink(missing_ok=True)
            remove_tree(DATA/'previews'/file_id)
            with db() as con:
                con.execute('DELETE FROM files WHERE id=?',(file_id,))
                con.execute("INSERT INTO chunk_fts(chunk_fts) VALUES('optimize')")
            with db() as con: con.execute('PRAGMA wal_checkpoint(TRUNCATE)')

    def retry(self,file_id,scope=None):
        with mutation_lock, db() as con:
            row=con.execute('SELECT * FROM files WHERE id=?',(file_id,)).fetchone()
            if not row or row['status'] in ('queued','processing'): return False
            if scope=='visual' and row['kind'] not in ('png','jpeg'): return False
            if scope is None:
                if row['status']!='failed' and not row['text_error'] and not row['visual_error']: return False
                scope='all' if row['text_error'] or row['status']=='failed' else 'visual'
            self.cancelled.discard(file_id)
            con.execute("UPDATE files SET status='queued',queue_scope=?,error=NULL WHERE id=?",(scope,file_id))
            return True

    @staticmethod
    def _available(con,file_id):
        return bool(con.execute('SELECT 1 FROM chunks WHERE file_id=? UNION ALL SELECT 1 FROM visual_vectors WHERE file_id=? LIMIT 1',(file_id,file_id)).fetchone())

    def run(self):
        while not self.stop.is_set():
            try:
                with mutation_lock, db() as con:
                    row=con.execute("SELECT * FROM files WHERE status='queued' ORDER BY created LIMIT 1").fetchone()
                    if row: con.execute("UPDATE files SET status='processing',error=NULL WHERE id=?",(row['id'],))
                if row: self.process_one(dict(row))
                else:
                    reconcile(DATA)
                    self.stop.wait(1)
            except Exception:
                log.exception('Queue error')
                self.stop.wait(1)

    def process_one(self,file):
        file_id,token=file['id'],uuid.uuid4().hex
        output=DATA/'work'/token
        scope=file.get('queue_scope','all')
        started=time.perf_counter()
        failure=None
        try:
            with mutation_lock:
                if self.stop.is_set() or file_id in self.cancelled or not get_file(file_id): return
                output.mkdir(parents=True)
                created=psutil.Process().create_time()
                (output/'owner.json').write_text(json.dumps({'parent_pid':os.getpid(),'parent_created':created,'file_id':file_id}),encoding='utf-8')
                with db() as con: con.execute('UPDATE files SET job_token=? WHERE id=?',(token,file_id))
                self.current_id=file_id
                env={**os.environ,'HF_HUB_OFFLINE':'1','HF_HUB_DISABLE_TELEMETRY':'1','TOKENIZERS_PARALLELISM':'false'}
                self.process=subprocess.Popen([sys.executable,'-m','backend.worker',str(DATA/'originals'/file_id),file['kind'],str(output),scope,str(os.getpid()),str(created)],
                    cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
                process=self.process
            try: process.wait(timeout=TIMEOUT)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)
                failure=f'Processing exceeded {TIMEOUT} seconds. Split the document or resize the image, then retry.'
            with mutation_lock:
                if not get_file(file_id) or file_id in self.cancelled: return
                if self.stop.is_set():
                    with db() as con: con.execute("UPDATE files SET status='queued' WHERE id=?",(file_id,))
                    return
                self.commit(file,output,scope,failure,time.perf_counter()-started)
        except Exception as exc:
            with db() as con:
                available=self._available(con,file_id)
                con.execute('UPDATE files SET status=?,error=? WHERE id=?',('ready' if available else 'failed',str(exc)[:600],file_id))
        finally:
            with mutation_lock:
                cleanup_job(output,DATA)
                self.current_id,self.process=None,None

    def commit(self,file,output,scope,failure,seconds):
        file_id=file['id']
        def result(capability):
            path=output/f'{capability}.json'
            return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'state':'failed','error':failure or 'Processing stopped unexpectedly. Check memory and retry.'}
        text=result('text') if scope in ('all','text') else None
        visual=result('visual') if scope in ('all','visual') and file['kind'] in ('png','jpeg') else None
        previews=list(output.glob('*.jpg'))
        if previews:
            dest=DATA/'previews'/file_id
            dest.mkdir(parents=True,exist_ok=True)
            for path in previews:
                staging=dest/(path.name+'.tmp')
                shutil.copyfile(path,staging)
                staging.replace(dest/path.name)
        with db() as con:
            if text:
                has_old=con.execute('SELECT 1 FROM chunks WHERE file_id=?',(file_id,)).fetchone()
                if text['state']=='ready' or (text['state']=='partial' and not has_old):
                    con.execute('DELETE FROM chunks WHERE file_id=?',(file_id,))
                    for c in text['chunks']:
                        con.execute('INSERT INTO chunks(file_id,page,text,boxes,method,vector,model,reference) VALUES(?,?,?,?,?,?,?,?)',
                            (file_id,c['page'],c['text'],json.dumps(c['boxes']),c['method'],np.asarray(c.get('vector',[]),dtype=np.float32).tobytes(),text.get('model') or '',c.get('reference')))
                    con.execute('UPDATE files SET pages=?,warning=?,model=? WHERE id=?',(text['pages'],text.get('warning'),text.get('model'),file_id))
                state=file['text_status'] if has_old and text['state'] in ('failed','partial') else text['state']
                con.execute('UPDATE files SET text_status=?,text_error=? WHERE id=?',(state,text.get('error'),file_id))
            if visual:
                old=con.execute('SELECT 1 FROM visual_vectors WHERE file_id=?',(file_id,)).fetchone()
                if visual['state']=='ready':
                    v=np.asarray(visual['vector'],dtype=np.float32)
                    if v.shape!=(512,) or not np.isfinite(v).all(): raise ValueError('Invalid visual index output.')
                    con.execute('INSERT OR REPLACE INTO visual_vectors(file_id,vector,model) VALUES(?,?,?)',(file_id,v.tobytes(),visual['model']))
                    con.execute('UPDATE files SET pages=1 WHERE id=?',(file_id,))
                state=visual['state'] if not old or visual['state']!='failed' else file['visual_status']
                con.execute('UPDATE files SET visual_status=?,visual_error=? WHERE id=?',(state,visual.get('error'),file_id))
            success=self._available(con,file_id) or (text and text['state']=='ready')
            errors=[r['error'] for r in (text,visual) if r and r.get('error')]
            con.execute('UPDATE files SET status=?,error=?,seconds=? WHERE id=?',('ready' if success else 'failed',' '.join(errors) or None,seconds,file_id))
