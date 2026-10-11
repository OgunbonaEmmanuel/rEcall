"""Ownership-aware staging cleanup, including orphan workers and Windows file handles."""
import json
import logging
import os
import re
import shutil
import time
from pathlib import Path
import psutil
from filelock import FileLock, Timeout
from .config import DATA, ROOT

log = logging.getLogger(__name__)

def same_process(pid, created):
    if not isinstance(pid,int) or pid <= 0 or not isinstance(created,(int,float)): return None
    try:
        process = psutil.Process(pid)
        return process if abs(process.create_time()-created)<.01 and process.is_running() else None
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return None

def guard_parent(pid, created):
    import threading
    def watch():
        while same_process(pid, created): time.sleep(.25)
        os._exit(90)
    threading.Thread(target=watch,daemon=True,name='parent-watch').start()

def safe_remove(path, data=DATA):
    path = Path(path)
    resolved = path.resolve()
    if not resolved.is_relative_to(data.resolve()) or resolved == data.resolve() or path.is_symlink():
        raise ValueError('Refusing to remove a path outside Recall data or through a symlink.')
    for attempt in range(6):
        try:
            if path.exists(): shutil.rmtree(path)
            return True
        except FileNotFoundError: return True
        except (PermissionError, OSError):
            if attempt == 5:
                log.warning('File handles still open; cleanup deferred: %s',path)
                return False
            time.sleep(.15*(attempt+1))

def workers_for(path):
    found=[]
    for process in psutil.process_iter(['pid','cmdline','cwd']):
        try:
            args=process.info['cmdline'] or []
            if 'backend.worker' not in args or Path(process.info['cwd'] or '').resolve()!=ROOT: continue
            output=Path(args[args.index('backend.worker')+3]).resolve()
            if output==path.resolve() or output.is_relative_to(path.resolve()): found.append(process)
        except (psutil.Error,IndexError,ValueError,OSError): continue
    return found

def cleanup_job(path,data=DATA):
    work=(data/'work').resolve()
    if path.is_symlink() or not path.resolve().is_relative_to(work) or path.resolve()==work:
        raise ValueError('Refusing cleanup outside the job work directory.')
    if not path.exists(): return True
    try: owner=json.loads((path/'owner.json').read_text(encoding='utf-8'))
    except (OSError,ValueError): owner={}
    if not isinstance(owner,dict): owner={}
    if owner.get('parent_pid')!=os.getpid() and same_process(owner.get('parent_pid'),owner.get('parent_created',-1)):
        return False
    for process in workers_for(path):
        try:
            parent=process.parent()
            if parent and parent.is_running() and parent.pid!=os.getpid():
                args=parent.cmdline()
                if 'uvicorn' in args and 'backend.app:app' in args: return False
            process.kill()
            process.wait(timeout=10)
        except psutil.NoSuchProcess: pass
        except (psutil.AccessDenied,psutil.TimeoutExpired): return False
    (data/'locks').mkdir(exist_ok=True)
    lock=FileLock(str(data/'locks'/f'{path.name}.lock'))
    try:
        with lock.acquire(timeout=0): removed=safe_remove(path,data)
        if removed: Path(lock.lock_file).unlink(missing_ok=True)
        return removed
    except (Timeout,PermissionError): return False

def reconcile(data=DATA):
    # Unknown paths and all originals/previews/database content are preserved.
    for path in (data/'work').iterdir():
        if (path.is_dir() and not path.is_symlink() and not path.is_junction()
                and re.fullmatch('[0-9a-f]{32}',path.name)):
            cleanup_job(path,data)
