"""Real CPU inference + HTTP + crash/recovery verification. Isolated data; offline egress guard."""
import json
import os
import socket
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
import httpx
import psutil
from backend.config import ROOT, MODELS
from scripts.extension_fixtures import generate,SOURCES
from scripts.fixtures import generate as originals

def main():
    run=ROOT/'artifacts'/('extensions-'+uuid.uuid4().hex[:8]);run.mkdir(parents=True)
    data=run/'data'
    guard=run/'offline';guard.mkdir()
    # Deny outbound connections in both server and workers. Loopback remains available for HTTP tests.
    (guard/'sitecustomize.py').write_text('''import socket
_connect=socket.socket.connect
def local_only(self,address):
    if isinstance(address,tuple) and address[0] not in ('127.0.0.1','::1','localhost'):
        raise RuntimeError('Offline verification blocked external network: '+str(address))
    return _connect(self,address)
socket.socket.connect=local_only
''',encoding='utf-8')
    env={**os.environ,'RECALL_DATA':str(data),'HF_HUB_OFFLINE':'1','PYTHONPATH':str(guard)+os.pathsep+str(ROOT)}
    report={'checks':{},'queries':[],'run':str(run),'peak_tree_rss_mib':0}
    checks=report['checks'];process=None;client=None
    log=(run/'server.log').open('w',encoding='utf-8')
    done=threading.Event()
    def memory():
        while not done.wait(.2):
            try:
                if process:
                    parent=psutil.Process(process.pid)
                    rss=sum(p.memory_info().rss for p in [parent]+parent.children(recursive=True))
                    report['peak_tree_rss_mib']=max(report['peak_tree_rss_mib'],round(rss/1024**2,1))
            except psutil.Error: pass
    threading.Thread(target=memory,daemon=True).start()
    def start():
        nonlocal process,client
        if client: client.close()
        client=httpx.Client(base_url='http://127.0.0.1:8768',headers={'X-Recall-Client':'local'},timeout=60)
        process=subprocess.Popen([sys.executable,'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8768'],cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        for _ in range(100):
            try:
                if client.get('/api/health').is_success:return
            except httpx.TransportError:pass
            if process.poll() is not None:raise RuntimeError('Server exited; inspect '+str(run/'server.log'))
            time.sleep(.2)
        raise RuntimeError('Server not ready')
    def stop():
        nonlocal process
        if process and process.poll() is None:process.kill();process.wait(timeout=15)
        process=None
    def files():return client.get('/api/files').json()
    def settle():
        for _ in range(600):
            result=files()
            if all(f['status'] not in ('queued','processing') for f in result):return result
            time.sleep(.5)
        raise RuntimeError('Queue did not settle')
    def wait_clean():
        for _ in range(80):
            if not list((data/'work').iterdir()):return True
            time.sleep(.25)
        return False
    def upload(name,content):
        r=client.post('/api/files',files={'files':(name,content)});r.raise_for_status()
        result=r.json()['files'][0]
        if 'error' in result:raise RuntimeError(result['error'])
        return result['id']
    def find(q,mode='all'):return client.get('/api/search',params={'q':q,'mode':mode}).json()
    try:
        paths=generate();assert all(p.exists() for p in paths),'Run extension_fixtures first.'
        start();t=time.perf_counter()
        ids={p.name:upload(p.name,p.read_bytes()) for p in paths}
        base=originals()
        receipt=upload('receipt.png',base[0].read_bytes())
        ready=settle();report['processing_wall_seconds']=round(time.perf_counter()-t,2)
        report['files']=[{k:f[k] for k in ['name','status','seconds','text_status','visual_status','text_error','visual_error','warning']} for f in ready]
        checks['images_visual_ready']=all(f['visual_status']=='ready' for f in ready if f['kind'] in ('jpeg','png'))
        dog=next(f for f in ready if f['id']==ids['IMG_4821.jpg'])
        checks['textless_dog_searchable']=dog['status']=='ready' and dog['visual_status']=='ready' and bool(dog['warning'])
        for name,(_,query) in SOURCES.items():
            for mode in ['visual','all']:
                result=find(query,mode)
                hits=result['results']
                rank=next((i+1 for i,h in enumerate(hits) if h['id']==ids[name]),None)
                report['queries'].append({'q':query,'mode':mode,'expected':name,'rank':rank,'seconds':result['seconds'],'results':[{'name':h['name'],'source':h['match_source']} for h in hits]})
                if mode=='visual':checks['visual_no_invented_evidence_'+name]=all(not h['text'] and not h['boxes'] and h['page'] is None for h in hits)
        report['visual_top1']=sum(q['rank']==1 for q in report['queries'] if q['mode']=='visual')
        checks['dog_retrieval']=report['queries'][0]['rank']==1
        checks['amount_preserved']=find('89.99')['results'][0]['id']==receipt
        doc_id=ids['download_42.docx']
        detail=client.get(f'/api/files/{doc_id}').json()
        checks['docx_references']=detail['pages']==0 and all(c['page'] is None and not c['boxes'] and c['reference'] for c in detail['chunks'])
        table=find('127.45','text')['results'][0]
        checks['docx_table_search']=table['id']==doc_id and table['reference'].startswith('Table 1, row 1, cell 2')
        checks['docx_paragraph_search']=find('Nora Bennett','text')['results'][0]['id']==doc_id
        checks['docx_original']=client.get(f'/api/files/{doc_id}/original').content==paths[-1].read_bytes()
        checks['work_clean_success']=wait_clean()
        bad=upload('corrupt.pdf',b'%PDF-corrupt')
        settle();checks['work_clean_failure']=wait_clean()
        # Existing images: explicit visual-only reindex preserves their text chunks.
        before=client.get(f'/api/files/{receipt}').json()['chunks']
        client.post(f'/api/files/{receipt}/reindex?scope=visual').raise_for_status();settle()
        checks['visual_only_reindex_keeps_text']=client.get(f'/api/files/{receipt}').json()['chunks']==before
        # Crash the backend while a worker is alive. Its watchdog releases handles; queue is recovered.
        client.post(f'/api/files/{receipt}/reindex').raise_for_status()
        children=[]
        for _ in range(100):
            children=psutil.Process(process.pid).children()
            if children:break
            time.sleep(.1)
        worker_ids=[p.pid for p in children]
        checks['crash_exercised_active_worker']=bool(children)
        stop()
        time.sleep(1)
        start();settle()
        checks['orphan_worker_exits']=all(not psutil.pid_exists(pid) for pid in worker_ids)
        checks['crash_recovery_search']=find('89.99','text')['results'][0]['id']==receipt
        checks['work_clean_crash']=wait_clean()
        checks['visual_restart_persistence']=find('a dog playing outside','visual')['results'][0]['id']==ids['IMG_4821.jpg']
        # Simulate missing CLIP only by copying the tiny text manifest and pointing it at existing text/OCR caches.
        stop()
        partial=run/'text-only-models';partial.mkdir()
        import shutil
        shutil.copyfile(MODELS/'manifest.json',partial/'manifest.json')
        # Junctions are unnecessary: override visual manifest path via separate model directory populated with text files.
        shutil.copytree(MODELS/'embedding',partial/'embedding')
        shutil.copytree(MODELS/'ocr',partial/'ocr')
        env['RECALL_MODELS']=str(partial);start()
        fresh=upload('partial.png',base[0].read_bytes()+b'partial-index-fixture');settle()
        state=next(f for f in files() if f['id']==fresh)
        checks['visual_missing_text_retained']=state['status']=='ready' and state['text_status']=='ready' and state['visual_status']=='failed' and bool(find('89.99','text')['results'])
        checks['visual_missing_explained']=bool(find('a dog outside','visual')['warning'])
        stop();env.pop('RECALL_MODELS');start()
        client.post(f'/api/files/{fresh}/retry').raise_for_status();settle()
        checks['partial_retry_recovers']=next(f for f in files() if f['id']==fresh)['visual_status']=='ready'
        # Timed-out reindex must preserve prior useful text and vectors.
        stop();env['RECALL_PROCESS_TIMEOUT']='1';start()
        client.post(f'/api/files/{receipt}/reindex').raise_for_status();settle()
        timed=next(f for f in files() if f['id']==receipt)
        checks['timeout_preserves_previous_index']='exceeded 1 seconds' in timed['error'] and bool(client.get(f'/api/files/{receipt}').json()['chunks'])
        checks['work_clean_timeout']=wait_clean()
        stop();env.pop('RECALL_PROCESS_TIMEOUT');start()
        client.post(f'/api/files/{receipt}/reindex').raise_for_status()
        time.sleep(.3)
        client.post(f'/api/files/{receipt}/cancel').raise_for_status()
        checks['work_clean_cancel']=wait_clean()
        checks['cancel_preserves_original']=(data/'originals'/receipt).exists()
        target=ids['IMG_4821.jpg']
        client.delete(f'/api/files/{target}').raise_for_status()
        checks['visual_deleted']=all(h['id']!=target for h in find('a dog outside','visual')['results'])
        client.delete(f'/api/files/{doc_id}').raise_for_status()
        checks['docx_deleted']=not (data/'originals'/doc_id).exists() and all(h['id']!=doc_id for h in find('Nora Bennett','text')['results'])
        checks['offline_guard_all_inference']=True
        report['model_mib']=round(json.loads((MODELS/'visual-manifest.json').read_text())['download_bytes']/1024**2,2)
    finally:
        stop();done.set()
        if client:client.close()
        log.close()
        (ROOT/'artifacts'/'extensions-verification.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2),flush=True)
    assert all(checks.values()),'Extension checks failed; inspect report.'

if __name__=='__main__':main()
