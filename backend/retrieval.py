"""Hybrid ranking over extracted source chunks, with honest source explanations."""
import re
import time
import numpy as np
from .storage import db, serialize_chunk
from .embeddings import embed, model_id

def snippet(text, query, terms):
    lower = text.casefold()
    position = lower.find(query)
    if position < 0:
        positions = [lower.find(t) for t in terms if len(t) > 2 and lower.find(t) >= 0]
        position = min(positions) if positions else 0
    start = max(0, position - 50)
    end = min(len(text), start + 220)
    return ('…' if start else '') + text[start:end].replace('\n', ' ') + ('…' if end < len(text) else '')

def text_search(query):
    start = time.perf_counter()
    query = query.strip()
    terms = re.findall(r'\w+', query.lower())
    if not terms:
        return {'results': [], 'warning': None, 'seconds': 0}
    warning, vector, identity = None, None, None
    try:
        identity = model_id()
        vector = embed([query])[0]
    except Exception as exc:
        warning = 'Semantic search unavailable; showing keyword matches only. ' + str(exc)[:300]
    phrase = query.casefold().strip('"')
    fts_query = ' OR '.join('"' + term + '"' for term in terms)
    with db() as con:
        lexical = {row['rowid'] for row in con.execute('SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH ?', (fts_query,))}
        rows = con.execute("SELECT c.*, f.name, f.kind, f.warning, f.demo FROM chunks c JOIN files f ON c.file_id=f.id").fetchall()
        files = con.execute("SELECT * FROM files").fetchall()
    best = {}
    mismatch = False
    for row in rows:
        text = row['text'].casefold()
        literal = phrase in text
        wordset = set(re.findall(r'\w+', text))
        coverage = sum(term in wordset for term in terms) / len(terms) if row['id'] in lexical else 0
        name_match = phrase in row['name'].casefold()
        cosine = 0.0
        if vector is not None and row['model'] == identity:
            candidate = np.frombuffer(row['vector'], dtype=np.float32)
            if candidate.shape == vector.shape:
                cosine = float(candidate @ vector)
        elif vector is not None:
            mismatch = True
        # Numeric-only queries require literal evidence; semantic similarity is weak for amounts.
        numeric = not any(c.isalpha() for c in query)
        keyword_match = literal or coverage >= .5 or name_match
        semantic_match = cosine >= .40 and not numeric
        if numeric and not literal and not name_match:
            continue
        if not keyword_match and not semantic_match:
            continue
        score = 3 * literal + 2 * name_match + 1.1 * coverage + max(0, cosine)
        match = 'Exact phrase' if literal else 'Filename' if name_match else 'Keyword match' if keyword_match else 'Semantic match'
        reason = {'Exact phrase': 'Your exact words appear in this source.', 'Filename': 'The original filename matches your search.',
                  'Keyword match': 'Search words appear in the extracted text.',
                  'Semantic match': 'Related meaning in the extracted text; your phrase does not appear literally.'}[match]
        result = {'id': row['file_id'], 'name': row['name'], 'kind': row['kind'], 'warning': row['warning'],
                  'demo': bool(row['demo']), 'match': match, 'reason': reason, 'match_source':'text',
                  **serialize_chunk(row), 'snippet': snippet(row['text'], phrase, terms), '_rank': score}
        if row['file_id'] not in best or score > best[row['file_id']]['_rank']:
            best[row['file_id']] = result
    # A textless file remains findable by its original name.
    for file in files:
        if phrase in file['name'].casefold() and file['id'] not in best:
            best[file['id']] = {'id': file['id'], 'name': file['name'], 'kind': file['kind'], 'warning': file['warning'],
                'demo': bool(file['demo']), 'match': 'Filename', 'reason': 'The original filename matches your search.',
                'page': None if file['kind']=='docx' else 1, 'text': '', 'boxes': [], 'method': '', '_rank': 2, 'match_source':'text'}
    results = sorted(best.values(), key=lambda item: -item['_rank'])[:30]
    for result in results:
        del result['_rank']
    if mismatch:
        warning = 'Some text embeddings are unavailable or use an older model. Keyword matches remain available; explicitly reindex affected files.'
    return {'results': results, 'warning': warning, 'seconds': round(time.perf_counter() - start, 3)}

def visual_search(query):
    from . import visual
    identity=visual.model_id()
    query_vector=visual.text_vector(query)
    with db() as con:
        rows=con.execute('SELECT f.*,v.vector,v.model AS visual_model FROM visual_vectors v JOIN files f ON f.id=v.file_id').fetchall()
    results=[]
    stale=False
    for row in rows:
        if row['visual_model']!=identity:
            stale=True
            continue
        vector=np.frombuffer(row['vector'],dtype=np.float32)
        if vector.shape!=query_vector.shape: continue
        similarity=float(vector@query_vector)
        if similarity<.23: continue
        results.append({'id':row['id'],'name':row['name'],'kind':row['kind'],'demo':bool(row['demo']),
                        'match':'Visual match','match_source':'visual','reason':'Related image content, matched locally with CLIP. No text evidence is inferred.',
                        'text':'','snippet':'','boxes':[],'page':None,'reference':None,'method':'CLIP image','_score':similarity})
    results.sort(key=lambda r:-r['_score'])
    for r in results: del r['_score']
    return {'results':results[:30],'warning':'Some visual indexes use an older model. Explicitly reindex these images.' if stale else None}

def search(query,mode='all'):
    started=time.perf_counter()
    warnings=[]
    text={'results':[]}
    images={'results':[]}
    if mode in ('all','text'):
        text=text_search(query)
        if text.get('warning'): warnings.append(text['warning'])
    # Numeric-only All queries retain literal evidence. Visual mode is always explicit.
    if mode=='visual' or (mode=='all' and any(c.isalpha() for c in query)):
        try:
            images=visual_search(query)
            if images.get('warning'): warnings.append(images['warning'])
        except Exception as exc:
            warnings.append('Visual search unavailable. '+str(exc)[:350])
    if mode=='visual': results=images['results']
    elif mode=='text': results=text['results']
    else:
        # Reciprocal rank fusion, k=60. Never add MiniLM and CLIP cosine values.
        merged={}
        for source,items in [('text',text['results']),('visual',images['results'])]:
            for rank,item in enumerate(items,1):
                if item['id'] not in merged: merged[item['id']]={**item,'_rrf':0}
                elif source=='visual':
                    merged[item['id']]['match_source']='both'
                    merged[item['id']]['reason']+=' Image content is also related to this query.'
                merged[item['id']]['_rrf']+=1/(60+rank)
        # Exact phrase/filename evidence stays ahead of fuzzy matches.
        results=sorted(merged.values(),key=lambda r:(r['match'] in ('Exact phrase','Filename'),r['_rrf']),reverse=True)
        for r in results: del r['_rrf']
    return {'results':results[:30],'warning':' '.join(warnings) or None,'seconds':round(time.perf_counter()-started,3),'mode':mode}
