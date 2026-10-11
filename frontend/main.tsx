import React, {useEffect, useRef, useState} from 'react';
import {createRoot} from 'react-dom/client';
import {Search, Upload, ArrowUpRight, ArrowRight, X, Files, Image as ImageIcon, FileText, Sparkles, LockKeyhole, CircleHelp, Check, LoaderCircle, RotateCcw, Trash2, Download, ChevronLeft, ChevronRight, FolderOpen, Plus, HardDrive, AlertCircle, ScanText} from 'lucide-react';
import './styles.css';
import './readability.css';
import './extensions.css';

type Box = {text: string; box: number[]};
type Chunk = {page: number|null; text: string; boxes: Box[]; method: string; reference?: string};
type Doc = {id: string; name: string; kind: string; size: number; status: 'queued'|'processing'|'ready'|'failed'; pages: number; text: string; error?: string; warning?: string; demo: boolean; seconds?: number; created: number; text_status?:string; visual_status?:string; text_error?:string; visual_error?:string};
type Hit = Doc & Chunk & {match: string; reason: string; snippet?: string; match_source?:'text'|'visual'|'both'};
type Detail = Doc & {chunks: Chunk[]};
async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {...init, headers: {'X-Recall-Client': 'local', ...init?.headers}});
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || `Request failed (${response.status}). Try again.`); }
  return response.json();
}
const previewUrl = (id: string, page = 1) => `/api/files/${id}/preview/${page}`;
const examples = ['headphone receipt', 'my hotel cancellation policy', 'how to care for my plants'];
function App() {
  const [docs, setDocs] = useState<Doc[]>([]), [initial, setInitial] = useState(true);
  const [query, setQuery] = useState(''), [submitted, setSubmitted] = useState('');
  const [mode, setMode] = useState('all');
  const modeRef = useRef('all');
  const [hits, setHits] = useState<Hit[]>([]), [searching, setSearching] = useState(false);
  const [filter, setFilter] = useState('all'), [collection, setCollection] = useState('all');
  const [notice, setNotice] = useState(''), [error, setError] = useState(''), [warning, setWarning] = useState('');
  const [uploading, setUploading] = useState(false), [dragging, setDragging] = useState(false);
  const [selected, setSelected] = useState<{id: string; page: number; source?: Hit}|null>(null);
  const [help, setHelp] = useState(false), [modelError, setModelError] = useState('');
  const inputRef = useRef<HTMLInputElement>(null), uploadRef = useRef<HTMLInputElement>(null);
  const requestId = useRef(0), latestSubmitted = useRef('');
  const previousStatus = useRef('');
  async function refresh() {
    try {
      const files = await api<Doc[]>('/api/files'); setDocs(files); setInitial(false);
      const signature = files.map(f => `${f.id}:${f.status}:${f.text_status}:${f.visual_status}`).join('|');
      if (previousStatus.current && signature !== previousStatus.current && latestSubmitted.current) void runSearch(latestSubmitted.current);
      previousStatus.current = signature;
    } catch (e) { setError((e as Error).message); setInitial(false); }
  }
  useEffect(() => {
    void refresh(); void api<{model_error: string;visual_error:string}>('/api/health').then(h => setModelError([h.model_error,h.visual_error].filter(Boolean).join(' '))).catch(e => setError(e.message));
    const interval = setInterval(() => void refresh(), 1800);
    const shortcut = (e: KeyboardEvent) => { if ((e.ctrlKey || e.metaKey) && e.key === 'k') { e.preventDefault(); inputRef.current?.focus(); } };
    window.addEventListener('keydown', shortcut);
    return () => { clearInterval(interval); window.removeEventListener('keydown', shortcut); };
  }, []);
  async function runSearch(value: string) {
    const text = value.trim(); const id = ++requestId.current;
    setSubmitted(text); latestSubmitted.current = text; setWarning(''); setError('');
    if (!text) { setHits([]); setSearching(false); return; }
    setSearching(true);
    try {
      const data = await api<{results: Hit[]; warning?: string}>(`/api/search?q=${encodeURIComponent(text)}&mode=${modeRef.current}`);
      if (id === requestId.current) { setHits(data.results); setWarning(data.warning || ''); }
    } catch (e) { if (id === requestId.current) { setHits([]); setError((e as Error).message); } }
    finally { if (id === requestId.current) setSearching(false); }
  }
  async function uploadFiles(files: FileList | File[]) {
    if (uploading || !files.length) return;
    setUploading(true); setError(''); setNotice('');
    const accepted: File[] = [], errors: string[] = [];
    for (const file of Array.from(files)) {
      if (!/\.(png|jpe?g|pdf|docx)$/i.test(file.name)) errors.push(`${file.name}: choose PNG, JPEG, PDF or DOCX. DOC and DOCM are unsupported.`);
      else if (file.size > 20 * 1024 * 1024) errors.push(`${file.name}: exceeds 20 MiB.`);
      else accepted.push(file);
    }
    let added = 0, duplicates = 0;
    try {
      for (let i = 0; i < accepted.length; i += 10) {
        const form = new FormData(); accepted.slice(i, i + 10).forEach(file => form.append('files', file));
        const data = await api<{files: {name: string; error?: string; duplicate?: boolean}[]}>('/api/files', {method: 'POST', body: form});
        for (const item of data.files) { if (item.error) errors.push(`${item.name}: ${item.error}`); else if (item.duplicate) duplicates++; else added++; }
      }
      setNotice(`${added} file${added === 1 ? '' : 's'} added${duplicates ? ` · ${duplicates} duplicate${duplicates === 1 ? '' : 's'} already in your library` : ''}.`);
      setError(errors.join(' ')); await refresh();
    } catch (e) { setError((e as Error).message); }
    finally { setUploading(false); if (uploadRef.current) uploadRef.current.value = ''; }
  }
  async function loadDemo() {
    setUploading(true); setError('');
    try { await api('/api/demo', {method: 'POST'}); setNotice('Synthetic demo collection added. Recall is reading the files locally.'); setCollection('demo'); await refresh(); }
    catch (e) { setError((e as Error).message); } finally { setUploading(false); }
  }
  async function retry(id: string) { try { await api(`/api/files/${id}/retry`, {method: 'POST'}); await refresh(); } catch(e) { setError((e as Error).message); } }
  const pending = docs.filter(d => ['processing', 'queued'].includes(d.status)).length;
  const filtered = (submitted ? hits : docs).filter(d => (filter === 'all' || (filter === 'image' ? ['png','jpeg'].includes(d.kind) : d.kind === filter)) && (collection !== 'demo' || d.demo) && (collection !== 'mine' || !d.demo));
  const chooseCollection = (value: string) => { setCollection(value); setQuery(''); void runSearch(''); };
  return <div className="app-shell">
    <aside className="sidebar">
      <a className="brand" href="/" aria-label="Recall home"><span className="brand-mark">r<span>↗</span></span>recall<span className="brand-dot">.</span></a>
      <div className="workspace-label"><span className="workspace-avatar">Y</span><div>Your space<small>Personal library</small></div><LockKeyhole size={14}/></div>
      <div className="nav-label">WORKSPACE</div>
      <nav aria-label="Collections">
        <button className={collection === 'all' ? 'nav-item active' : 'nav-item'} onClick={() => chooseCollection('all')}><Files size={19}/>All files<span>{docs.length}</span></button>
        <button className={collection === 'mine' ? 'nav-item active' : 'nav-item'} onClick={() => chooseCollection('mine')}><FolderOpen size={19}/>My uploads<span>{docs.filter(d => !d.demo).length}</span></button>
        <button className={collection === 'demo' ? 'nav-item active' : 'nav-item'} onClick={() => chooseCollection('demo')}><Sparkles size={19}/>Demo collection<span className="tiny-pill">TRY IT</span></button>
      </nav>
      <div className="sidebar-note"><div className="mini-orbit"><Search size={22}/><span>✦</span></div><h3>A little less searching.<br/>A little more finding.</h3><p>Your files, connected to the words you remember.</p></div>
      <div className="sidebar-bottom"><div className="local-label"><span/>Stored on this device</div><p>Your files stay yours. Processing<br/>happens right here.</p><button onClick={() => setHelp(true)}><CircleHelp size={16}/>How Recall works<ArrowUpRight size={14}/></button></div>
    </aside>
    <main>
      <header className="topbar"><div><span className="breadcrumb">Your workspace</span><ChevronRight size={14}/><span>{collection === 'demo' ? 'Demo collection' : collection === 'mine' ? 'My uploads' : 'All files'}</span></div><span className="private-badge"><LockKeyhole size={13}/>Local & private</span></header>
      <div className="main-content">
        <section className="hero"><div className="eyebrow"><span/>A HOME FOR WHAT YOU SAVE</div><h1>Remember a little.<br/><span>Find the whole thing.</span></h1><p>That receipt. That screenshot. That thing you saved.<br className="desktop-break"/> Find it with the words that come to mind.</p>
          <form className="search-form" onSubmit={e => {e.preventDefault(); void runSearch(query);}}><Search size={23}/><input ref={inputRef} aria-label="Search your files" maxLength={300} placeholder="What do you remember?" value={query} onChange={e => setQuery(e.target.value)}/>{query ? <button type="button" className="clear-search" aria-label="Clear search" onClick={() => {setQuery(''); void runSearch('');}}><X size={17}/></button> : <kbd>Ctrl K</kbd>}<button type="submit" className="search-submit" aria-label="Search" disabled={searching}>{searching ? <LoaderCircle className="spin" size={20}/> : <ArrowRight size={21}/>}</button></form>
          <div className="search-modes" role="group" aria-label="Search mode">{[['all','All'],['text','Text'],['visual','Visual']].map(([key,label])=><button key={key} aria-pressed={mode===key} onClick={()=>{modeRef.current=key;setMode(key);void runSearch(query);}}>{label}</button>)}</div><p className="mode-help">{mode==='visual' ? 'Search what standalone images show, even without words.' : mode==='text' ? 'Search extracted text and original filenames.' : 'Search text and image contents together.'}</p><div className="examples"><span>Try a memory</span>{examples.map(example => <button key={example} onClick={() => {setQuery(example); void runSearch(example);}}>{example}<ArrowUpRight size={12}/></button>)}</div>
        </section>
        <input id="file-upload" ref={uploadRef} className="sr-only" tabIndex={-1} type="file" accept=".png,.jpg,.jpeg,.pdf,.docx" multiple onChange={e => e.target.files && void uploadFiles(e.target.files)}/>
        <section className={`upload-area ${dragging ? 'dragging' : ''}`} onDragOver={e => {e.preventDefault(); setDragging(true);}} onDragLeave={() => setDragging(false)} onDrop={e => {e.preventDefault(); setDragging(false); void uploadFiles(e.dataTransfer.files);}} aria-label="Upload files">
          <div className="upload-icon">{uploading ? <LoaderCircle className="spin" size={25}/> : <Upload size={25}/>}</div><div><h2>{uploading ? 'Adding your files…' : 'Drop it here. Find it later.'}</h2><p>PNG, JPG, PDF or DOCX <span>·</span> Up to 20 MiB per file <span>·</span> 20 pages per PDF</p></div><button className="button primary" disabled={uploading} onClick={() => uploadRef.current?.click()}><Plus size={17}/>Add files</button>
        </section>
        {modelError && <div className="alert error"><AlertCircle size={18}/><span>{modelError}</span></div>}
        {error && <div className="alert error" role="alert"><AlertCircle size={18}/><span>{error}</span><button aria-label="Dismiss error" onClick={() => setError('')}><X size={16}/></button></div>}
        {notice && <div className="alert success" role="status"><Check size={17}/><span>{notice}</span><button aria-label="Dismiss notification" onClick={() => setNotice('')}><X size={16}/></button></div>}
        {pending > 0 && <div className="processing-banner" role="status"><LoaderCircle className="spin" size={17}/><span>Making {pending} file{pending === 1 ? '' : 's'} searchable…</span><small>You can keep searching while we work.</small></div>}
        {warning && <div className="alert" role="status"><AlertCircle size={17}/><span>{warning}</span></div>}
        <section className="library" aria-label="File library" aria-busy={searching || initial}>
          <div className="library-heading"><div><h2>{submitted ? 'What we found' : collection === 'demo' ? 'Demo collection' : collection === 'mine' ? 'My uploads' : 'Your library'}<span>{filtered.length}</span></h2><p>{submitted ? `Matches for “${submitted}”` : collection === 'demo' ? 'Synthetic files made for exploring. No real personal information.' : 'A little of everything, all within reach.'}</p></div><div className="filter-tabs" aria-label="File type">{[['all','All files'],['image','Images'],['pdf','PDFs'],['docx','DOCX']].map(([key,label]) => <button key={key} aria-pressed={filter === key} className={filter === key ? 'selected' : ''} onClick={() => setFilter(key)}>{label}</button>)}</div></div>
          {initial || searching ? <div className="file-grid">{[1,2,3].map(i => <div key={i} className="skeleton"/>)}</div> : filtered.length ? <div className="file-grid">{filtered.map(doc => <FileCard key={doc.id} doc={doc} onOpen={() => setSelected({id: doc.id, page: (doc as Hit).page || 1, source: submitted ? doc as Hit : undefined})} onRetry={() => void retry(doc.id)}/>)}</div> : <div className="empty-state"><div className="empty-art"><FolderOpen size={44}/><Search size={25}/></div><h3>{submitted ? 'No files found just yet' : collection === 'mine' ? 'Your next find starts here' : 'Make room for a little recall'}</h3><p>{submitted ? 'Try a name, a phrase, or a few different words. Files need to finish processing before they appear.' : 'Add screenshots and documents, or explore a collection of synthetic examples to see how it works.'}</p>{submitted ? <button className="button secondary" onClick={() => {setQuery(''); void runSearch('');}}>Back to your library</button> : <div className="empty-actions"><button className="button primary" onClick={() => uploadRef.current?.click()}><Plus size={16}/>Add your first files</button><button className="button secondary" disabled={uploading} onClick={() => void loadDemo()}><Sparkles size={16}/>Try demo collection</button></div>}</div>}
        </section>
        {docs.length > 0 && !docs.some(d => d.demo) && <button className="demo-strip" onClick={() => void loadDemo()} disabled={uploading}><Sparkles size={19}/><span>Curious what Recall can find?<small>Explore 10 synthetic demo files.</small></span><ArrowRight size={18}/></button>}
        <footer><span><HardDrive size={14}/>On your device. In your control.</span><span>Made for the things you almost remember.</span></footer>
      </div>
    </main>
    {selected && <Preview selected={selected} onClose={() => setSelected(null)} onDelete={async () => {await api(`/api/files/${selected.id}`, {method:'DELETE'}); setSelected(null); setNotice('File deleted, including its original, previews, text and search entries.'); await refresh();}}/>}
    {help && <Help onClose={() => setHelp(false)}/>}
  </div>;
}

function FileCard({doc, onOpen, onRetry}: {doc: Doc|Hit; onOpen: () => void; onRetry: () => void}) {
  const status = doc.status || 'ready', hit = doc as Hit;
  const pending = status === 'queued' || status === 'processing';
  return <article className="file-card"><button className={`thumbnail type-${doc.kind}`} onClick={onOpen} aria-label={`Preview ${doc.name}`} >
    {doc.kind === 'docx' ? <div className="docx-thumbnail"><FileText size={35}/><span>Word document</span><small>Paragraphs & tables</small></div> : status === 'ready' ? <img src={previewUrl(doc.id, hit.page || 1)} alt="" loading="lazy"/> : <div className="thumbnail-state">{pending ? <LoaderCircle className="spin" size={27}/> : <AlertCircle size={27}/>}<span>{status === 'queued' ? 'Waiting in line' : status === 'processing' ? 'Reading your file' : 'Needs attention'}</span></div>}
    <span className="file-type">{['pdf','docx'].includes(doc.kind) ? <FileText size={12}/> : <ImageIcon size={12}/>} {doc.kind.toUpperCase()}{hit.page && doc.kind === 'pdf' ? ` · PAGE ${hit.page}` : ''}</span>{doc.demo && <span className="demo-tag">DEMO</span>}<span className="preview-hover">Preview<ArrowUpRight size={16}/></span>
    </button><div className="card-body"><button className="file-name" onClick={onOpen} title={doc.name} >{doc.name}</button>{hit.match && <div className={`match-label ${hit.match === 'Semantic match' ? 'semantic' : ''}`}>{hit.match === 'Semantic match' ? <Sparkles size={12}/> : <ScanText size={12}/>} {hit.match}{hit.match_source === 'both' ? ' · Text + visual' : ''}{hit.reference ? ` · ${hit.reference}` : hit.page ? ` · Page ${hit.page}` : ''}</div>}<p className="snippet">{(hit.match_source === 'visual' ? 'Matched image contents. No text excerpt.' : doc.text_error || doc.visual_error || doc.warning || hit.snippet || doc.text) || (pending ? 'Extracting text and connecting the dots…' : 'No readable text found.')}</p>{hit.reason && <p className="match-reason">{hit.reason}</p>}<div className="card-bottom"><span className={`status ${status}`}><span/>{doc.visual_status === 'ready' && doc.warning ? 'Visually searchable' : doc.warning ? 'Limited readable text' : status === 'ready' ? 'Ready to find' : status.charAt(0).toUpperCase() + status.slice(1)}</span>{(status === 'failed' || doc.text_error || doc.visual_error) && !pending ? <button className="retry" onClick={onRetry}><RotateCcw size={13}/>Retry</button> : <span>{doc.kind === 'docx' ? 'DOCX sources' : doc.pages ? `${doc.pages} page${doc.pages === 1 ? '' : 's'}` : hit.page ? 'Source match' : ''}</span>}</div></div></article>;
}

function useDialog(ref: React.RefObject<HTMLDialogElement|null>, onClose: () => void) {
  useEffect(() => {const previous = document.activeElement as HTMLElement; ref.current?.showModal(); return () => {ref.current?.close(); previous?.focus();};}, []);
  return {onCancel: (e: React.SyntheticEvent) => {e.preventDefault(); onClose();}};
}
function Preview({selected,onClose,onDelete}: {selected: {id:string;page:number;source?:Hit};onClose:()=>void;onDelete:()=>Promise<void>}) {
  const dialog = useRef<HTMLDialogElement>(null), dialogProps = useDialog(dialog,onClose);
  const [doc,setDoc] = useState<Detail|null>(null), [page,setPage] = useState(selected.page);
  const [error,setError] = useState(''), [confirm,setConfirm] = useState(false), [deleting,setDeleting] = useState(false);
  useEffect(() => {
    const read=()=>void api<Detail>(`/api/files/${selected.id}`).then(setDoc).catch(e=>setError(e.message));
    read(); const timer=setInterval(read,1800); return ()=>clearInterval(timer);
  }, [selected.id]);
  const isDocx=doc?.kind==='docx';
  const visualOnly=selected.source?.match_source==='visual';
  const source=(isDocx || visualOnly || selected.source?.page===page) ? selected.source : null;
  const chunks=doc?.chunks.filter(c=>isDocx || c.page===page) || [];
  const pending=doc?.status==='queued' || doc?.status==='processing';
  async function action(endpoint:string) {
    try {await api(`/api/files/${selected.id}/${endpoint}`,{method:'POST'});setDoc(await api<Detail>(`/api/files/${selected.id}`));}
    catch(e){setError((e as Error).message);}
  }
  return <dialog className="preview-dialog" ref={dialog} {...dialogProps} aria-labelledby="preview-title">
    <div className="modal-top"><div><span className="eyebrow">SOURCE PREVIEW</span><h2 id="preview-title">{doc?.name || 'Loading file…'}</h2></div>
      <button className="icon-button" aria-label="Close preview" onClick={onClose}><X size={21}/></button></div>
    {error && <div className="alert error" role="alert">{error}</div>}
    {doc ? <>
      <div className="capability-strip">
        <span>Text: {doc.text_status}</span>
        {['png','jpeg'].includes(doc.kind) && <span>Visual: {doc.visual_status}</span>}
        {pending ? <button className="button secondary" onClick={()=>void action('cancel')}>Cancel processing</button> :
          <><button className="button secondary" onClick={()=>void action('reindex?scope=text')}>Reindex text</button>
          {['png','jpeg'].includes(doc.kind) && <button className="button secondary" onClick={()=>void action('reindex?scope=visual')}>Reindex visual</button>}</>}
      </div>
      {(doc.text_error || doc.visual_error || doc.error) && <div className="alert" role="status">{[doc.text_error,doc.visual_error].filter(Boolean).join(' ') || doc.error}</div>}
      <div className="preview-layout">
        <div className="preview-pane">
          {isDocx ? <div className="docx-text-preview" aria-label="DOCX text preview">
            <p>Body text preview · layout and page numbers are not inferred</p>
            {doc.chunks.map((c,i)=><section key={i}><h3>{c.reference}</h3><p>{c.text}</p></section>)}
            {!doc.chunks.length && <p>No extracted body text yet.</p>}
          </div> : doc.pages>0 ? <div className="page-image">
            <img src={previewUrl(doc.id,page)} alt={doc.kind==='pdf' ? `Page ${page} of ${doc.name}` : doc.name}/>
            {!visualOnly && source?.boxes.map((box,i)=><span key={i} className="source-box" style={{left:`${box.box[0]*100}%`,top:`${box.box[1]*100}%`,width:`${(box.box[2]-box.box[0])*100}%`,height:`${(box.box[3]-box.box[1])*100}%`}}/>)}
          </div> : <div className="empty-state"><AlertCircle size={30}/><p>{doc.error || 'Preview will appear after processing.'}</p></div>}
        </div>
        <div className="source-text">
          <span className="pill">{doc.kind.toUpperCase()}{isDocx ? ' · Paragraphs & tables' : doc.kind==='pdf' ? ` · Page ${page} of ${doc.pages || 1}` : ' · Image'}</span>
          {doc.demo && <p className="demo-disclaimer">Synthetic demo document</p>}
          <h3>{source ? source.match : isDocx ? 'Text from this document' : 'Text from this page'}</h3>
          <p>{source ? source.reason : 'Read directly from your file. OCR may contain mistakes.'}</p>
          {doc.warning && !visualOnly && <div className="alert">{doc.warning}</div>}
          {visualOnly ? <div className="visual-evidence"><ImageIcon size={28}/><p>This match comes from image contents. No text excerpt or source highlight is inferred.</p></div> :
            <><div className="extracted-text">{source?.text || chunks.map(c=>c.text).join('\n\n') || 'No readable text in this source.'}</div>
            <div className="source-method"><ScanText size={14}/>{source?.reference || (isDocx ? 'DOCX body paragraphs and tables' : `${chunks[0]?.method || 'Text extraction'} · Source page ${page}`)}</div></>}
        </div>
      </div>
      <div className="modal-bottom">
        {doc.kind==='pdf' ? <div className="page-controls">
          <button className="icon-button" aria-label="Previous page" disabled={page<=1} onClick={()=>setPage(page-1)}><ChevronLeft size={19}/></button>
          <span>Page {page} / {doc.pages || 1}</span>
          <button className="icon-button" aria-label="Next page" disabled={page>=(doc.pages || 1)} onClick={()=>setPage(page+1)}><ChevronRight size={19}/></button>
        </div> : <span className="source-method">{isDocx ? 'Document references, not page numbers' : 'Original image'}</span>}
        <div className="modal-actions"><button className="button danger" disabled={deleting} onClick={()=>setConfirm(true)}><Trash2 size={15}/>Delete</button>
          <a className="button primary" href={`/api/files/${doc.id}/original`} download><Download size={15}/>Download original</a></div>
      </div>
      {confirm && <div className="delete-confirm" role="alert"><span>Delete this file and all its search data permanently?</span>
        <button className="button secondary" onClick={()=>setConfirm(false)}>Keep file</button>
        <button className="button danger" disabled={deleting} onClick={async()=>{setDeleting(true);try{await onDelete();}catch(e){setError((e as Error).message);setDeleting(false);}}}>{deleting ? 'Deleting…' : 'Delete permanently'}</button></div>}
    </> : <div className="empty-state"><LoaderCircle className="spin"/></div>}
  </dialog>;
}
function Help({onClose}: {onClose:()=>void}) {
  const ref=useRef<HTMLDialogElement>(null), props=useDialog(ref,onClose);
  return <dialog ref={ref} {...props} className="help-dialog" aria-labelledby="help-title"><button className="icon-button help-close" onClick={onClose} aria-label="Close help"><X size={20}/></button><span className="eyebrow">A SMALL GUIDE</span><h2 id="help-title">A memory is a good start.</h2><p>Recall searches extracted text and filenames in Text mode, image contents in Visual mode, and combines ranked results in All.</p><ol><li><strong>Add your files.</strong> PNG, JPEG, PDF or DOCX. Up to 20 MiB, 20 PDF pages and 25 megapixels per image. DOCX is limited to 1,000 archive entries, 50 MiB expanded data, 8 MiB per XML part and 200,000 extracted characters.</li><li><strong>Give them a moment.</strong> Files are processed one at a time on your CPU, with a 120-second limit per file. Failed files can be retried.</li><li><strong>Describe what you remember.</strong> A name, an amount or a description. Open a result to see its source page and extracted text.</li></ol><p>Semantic matches suggest related meaning; they are not guarantees. Check the original, especially for amounts. Visual mode uses image contents with local CLIP encoders. DOCX uses paragraph/table references; pagination is not inferred. DOCX headers, footers, text boxes and embedded-image OCR are not supported.</p><div className="privacy-note"><LockKeyhole size={20}/><p>Your originals, previews and search data stay on this device. Public model weights are downloaded once during setup. Your files are never uploaded to an AI service.</p></div><button className="button primary" onClick={onClose}>Got it<Check size={16}/></button></dialog>;
}
createRoot(document.getElementById('root')!).render(<App/>);

