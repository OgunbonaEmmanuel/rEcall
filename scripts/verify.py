"""Actual HTTP + worker + disk + restart verification against isolated synthetic data."""
import json
import os
import platform
import subprocess
import sys
import time
import uuid
from pathlib import Path
import httpx
from backend.config import ROOT
from scripts.fixtures import generate, EXPECTED

def main():
    run_dir = ROOT / 'artifacts' / ('verify-' + uuid.uuid4().hex[:8])
    run_dir.mkdir(parents=True)
    env = {**os.environ, 'RECALL_DATA': str(run_dir / 'data'), 'HF_HUB_OFFLINE': '1'}
    report = {'environment': {'python': platform.python_version(), 'platform': platform.platform(), 'cpu': platform.processor(), 'cpu_count': os.cpu_count()}, 'checks': {}, 'queries': []}
    log = (run_dir / 'server.log').open('w', encoding='utf-8')
    client = httpx.Client(base_url='http://127.0.0.1:8766', headers={'X-Recall-Client':'local'}, timeout=40)
    process = None
    def start():
        nonlocal process, client
        client.close()
        client = httpx.Client(base_url='http://127.0.0.1:8766', headers={'X-Recall-Client':'local'}, timeout=40)
        process = subprocess.Popen([sys.executable,'-m','uvicorn','backend.app:app','--host','127.0.0.1','--port','8766'], cwd=ROOT, env=env, stdout=log, stderr=log,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        for _ in range(100):
            try:
                if client.get('/api/health').is_success: return
            except httpx.TransportError: pass
            if process.poll() is not None: raise RuntimeError('Server exited; see log.')
            time.sleep(.2)
        raise RuntimeError('Server did not become ready.')
    def stop():
        nonlocal process
        if process and process.poll() is None:
            process.terminate(); process.wait(timeout=15)
        process = None
    def settle():
        for _ in range(600):
            files = client.get('/api/files').json()
            if all(f['status'] not in ['queued','processing'] for f in files): return files
            time.sleep(.5)
        raise RuntimeError('Processing did not finish in five minutes.')
    try:
        start()
        paths = generate()
        start_time = time.perf_counter()
        response = client.post('/api/files', files=[('files',(p.name,p.read_bytes())) for p in paths])
        response.raise_for_status()
        ids = {x['name']: x['id'] for x in response.json()['files']}
        ready = settle()
        report['processing_wall_seconds'] = round(time.perf_counter()-start_time,3)
        report['files'] = [{k:f[k] for k in ['name','status','seconds','warning','pages','error']} for f in ready]
        report['checks']['ten_ready'] = len(ready)==10 and all(f['status']=='ready' for f in ready)
        report['checks']['unreadable_warning'] = bool(next(f for f in ready if f['name']=='IMG_0000.png')['warning'])
        for query, expected, page in EXPECTED:
            data = client.get('/api/search',params={'q':query}).json()
            hits = data['results']
            rank = next((i+1 for i,hit in enumerate(hits) if hit['name']==expected), None)
            report['queries'].append({'query':query,'expected':expected,'expected_page':page,'rank':rank,'seconds':data['seconds'],
                                     'results':[{'name':h['name'],'page':h['page'],'match':h['match']} for h in hits[:5]], 'warning':data['warning']})
        report['checks']['top1'] = sum(q['rank']==1 for q in report['queries'])
        report['checks']['top3'] = sum(q['rank'] is not None and q['rank']<=3 for q in report['queries'])
        duplicate = client.post('/api/files',files={'files':('duplicate.png',paths[0].read_bytes())}).json()['files'][0]
        report['checks']['duplicate'] = duplicate['duplicate'] and duplicate['id']==ids[paths[0].name]
        # Raw traversal-looking upload name stays metadata, never a disk path.
        malformed = client.post('/api/files',files={'files':('../../unsafe.pdf', b'%PDF-1.7\ncorrupt')}).json()['files'][0]
        failed = next(f for f in settle() if f['id']==malformed['id'])
        report['checks']['corrupt_failed'] = failed['status']=='failed' and bool(failed['error'])
        report['checks']['filename_safe'] = failed['name']=='../../unsafe.pdf' and not (run_dir/'unsafe.pdf').exists() and (run_dir/'data'/'originals'/malformed['id']).exists()
        retry = client.post(f"/api/files/{malformed['id']}/retry")
        report['checks']['retry_accepted'] = retry.is_success
        report['checks']['retry_failure_visible'] = next(f for f in settle() if f['id']==malformed['id'])['status']=='failed'
        report['checks']['mutations_guarded'] = client.post('/api/demo',headers={'X-Recall-Client':''}).status_code==403
        report['checks']['cross_origin_guarded'] = client.post('/api/demo',headers={'Origin':'https://example.com'}).status_code==403
        report['checks']['invalid_content_rejected'] = bool(client.post('/api/files',files={'files':('fake.png',b'<script>alert(1)</script>')}).json()['files'][0]['error'])
        report['checks']['page_source_boxes'] = bool(client.get(f"/api/files/{ids['scan_023.pdf']}").json()['chunks'][0]['boxes'])
        stop(); start()
        persisted = client.get('/api/files').json()
        found = client.get('/api/search',params={'q':'headphone receipt'}).json()['results']
        report['checks']['restart_persistence'] = len(persisted)==11 and found[0]['id']==ids['IMG_4821.png']
        target = ids['IMG_4821.png']
        delete = client.delete(f'/api/files/{target}')
        found = client.get('/api/search',params={'q':'headphone receipt'}).json()['results']
        report['checks']['deletion'] = delete.is_success and all(h['id']!=target for h in found) and not any((run_dir/'data'/folder/target).exists() for folder in ['originals','previews','work'])
        report['checks']['deleted_original_404'] = client.get(f'/api/files/{target}/original').status_code==404
        stop(); start()
        report['checks']['deletion_persists'] = all(f['id']!=target for f in client.get('/api/files').json())
        report['checks']['no_results'] = client.get('/api/search',params={'q':'zxqv778899 nonexistent unicorn astronaut'}).json()['results']==[]
        # A missing model must fail visibly without partial searchable data; retry after setup recovers.
        stop(); env['RECALL_MODELS'] = str(run_dir/'missing-models'); start()
        missing_id = client.post('/api/files', files={'files':('recoverable.png', paths[0].read_bytes())}).json()['files'][0]['id']
        missing_file = next(f for f in settle() if f['id']==missing_id)
        detail = client.get(f'/api/files/{missing_id}').json()
        report['checks']['missing_model_atomic_failure'] = missing_file['status']=='failed' and 'model' in missing_file['error'].lower() and not detail['chunks']
        report['checks']['missing_model_keyword_fallback'] = bool(client.get('/api/search',params={'q':'Maya Chen'}).json()['warning'])
        stop(); env.pop('RECALL_MODELS'); start()
        client.post(f'/api/files/{missing_id}/retry').raise_for_status()
        report['checks']['retry_after_model_recovery'] = next(f for f in settle() if f['id']==missing_id)['status']=='ready'
        # Force a real worker timeout, then resume under the documented default budget.
        stop(); env['RECALL_PROCESS_TIMEOUT']='1'; start()
        timeout_id = client.post('/api/files',files={'files':('timeout.png',paths[0].read_bytes()+b'recall-timeout-fixture')}).json()['files'][0]['id']
        timed = next(f for f in settle() if f['id']==timeout_id)
        report['checks']['real_timeout'] = timed['status']=='failed' and 'exceeded 1 seconds' in timed['error']
        stop(); env.pop('RECALL_PROCESS_TIMEOUT'); start()
        client.post(f'/api/files/{timeout_id}/retry').raise_for_status()
        report['checks']['timeout_retry_recovers'] = next(f for f in settle() if f['id']==timeout_id)['status']=='ready'
    finally:
        stop(); log.close(); client.close()
        report_path = ROOT/'artifacts'/'verification.json'
        report_path.write_text(json.dumps(report,indent=2),encoding='utf-8')
        print(json.dumps(report,indent=2),flush=True)
        print(f'Report: {report_path}',flush=True)
    assert all(value is True for key,value in report['checks'].items() if key not in ['top1','top3']), 'Some verification checks failed; see report.'

if __name__=='__main__': main()
