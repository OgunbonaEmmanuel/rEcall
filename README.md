# Recall

Recall helps people find saved screenshots, photos and documents whose filenames are hard to remember. **Manually upload PNG, JPEG, PDF or DOCX files**, then search using exact words, an amount or a description of what you remember. Recall does not scan your computer.

Processing and search run locally on your CPU after setup, without an API key or an external AI service. Results retrieve supporting files and actual text excerpts where available; Recall does not generate answers.

## Demo

[Open the recorded Recall demo — MP4, 20.24 MiB](example_vid/Recall%20%E2%80%94%20Find%20what%20you%20remember%20%28127.0.0.1_8765%29%20-%20recall%20-%20Visual%20Studio%20Code%20%5BAdministrator%5D%202026-10-11%2015-23-23.mp4)

This is a relative link to the recording in the repository. Open or download the file to watch; inline playback is not assumed.

## Search examples

These illustrate ways to search your own uploaded collection, not guaranteed matches.

| Mode | Example query | What it can help find |
| --- | --- | --- |
| **Visual** | “a dog playing outside” | A textless dog photo with an unhelpful filename such as `IMG_4821.jpg` |
| **Text** | “proof I paid for wireless audio gear” | A document whose extracted text describes a headphone purchase |
| **All** | `89.99` | A receipt containing that exact amount in readable, extracted text |

**Text** searches extracted content and original filenames, including paraphrases of readable text. **Visual** searches the contents of standalone PNG/JPEG images, even without readable text. **All** combines the two rankings, prioritizing literal evidence; numeric-only All queries use text/filename evidence rather than image similarity.

A visually similar image does not prove every action or detail in a query. The [recorded evaluation](VERIFICATION.md#visual-retrieval-with-distractors) includes both successful retrievals and a false positive.

## Setup

### Prerequisites

These instructions target **Windows x64 and PowerShell**. You need Python with `venv`/`pip`, Node.js with npm, internet access for initial dependency/model downloads, and disk space for dependencies, models and your files.

The tested configuration was **Windows 10 x64, Python 3.13.0, Node 20.18.0 and npm 10.8.2**. The lock files record the tested dependencies, including FastEmbed 0.8.1 and ONNX Runtime 1.31.0. Use that configuration to reproduce the documented setup; other versions and operating systems have not been verified. These are tested versions, not a minimum compatibility matrix.

No GPU, API key, account, Tesseract installation or hosted database is required. Microsoft Edge is needed only for the documented browser test scripts.

### First-time setup

Clone the repository using its GitHub **Code** menu or your Git client, then open PowerShell. Replace the example path below with your cloned project directory. The explicit Python path avoids needing to activate the virtual environment.

```powershell
Set-Location -LiteralPath 'C:\path\to\recall'
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.lock.txt
npm ci --no-fund --no-audit
.venv/Scripts/python -m scripts.setup_models
.venv/Scripts/python -m scripts.setup_visual
npm run build
.venv/Scripts/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765** once the server starts.

### What model setup installs

**Model caches are excluded from Git and are not included when you clone this repository.** Neither are Python/npm dependencies, the frontend build or uploaded documents.

| Setup command | Local model files | Measured disk storage |
| --- | --- | ---: |
| `.venv/Scripts/python -m scripts.setup_models` | Downloads MiniLM text embeddings; copies bundled RapidOCR ONNX models into `.models/ocr` | About **117 MiB** |
| `.venv/Scripts/python -m scripts.setup_visual` | Downloads paired CLIP text/image encoders into `.models/visual` | **579.85 MiB** |

Together these caches occupy about **697 MiB on disk**; this does not include application dependencies, originals, previews or RAM usage. Setup writes model manifests and fingerprints. It reads no user documents and uploads none. Downloads expose normal connection information, such as your IP address, to their hosts.

Package installation and initial model downloads require internet. Normal app runtime uses cached models only and does not send files or queries to an external provider. There is no external inference fallback. See [troubleshooting](#troubleshooting) before assuming rerunning setup will repair a damaged cache.

### Running again

After completing setup, start the existing installation without reinstalling dependencies or downloading models:

```powershell
Set-Location -LiteralPath 'C:\path\to\recall'
.venv/Scripts/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765**. Alternatively, `.\run.ps1` starts the same command from the script's directory after checking for the virtual environment and frontend build. It does not install dependencies, download models or rebuild assets. If PowerShell blocks scripts, use the Python command above.

Keep the terminal open while using Recall. **Ctrl+C stops the backend.** Use one server process per data directory, without `--reload` or multiple Uvicorn workers.

Recall is a local, single-user app without authentication. Keep it bound to loopback (`127.0.0.1`); do not deploy it publicly.

## Everyday use

Use **Add files** or drag and drop. Original names are preserved as metadata, filesystem paths use generated stable IDs, and identical bytes deduplicate to the existing document. **Try demo collection** loads ten clearly labelled synthetic image/PDF files locally; it does not fetch public photos.

Wait for queued/processing files to finish, then search. Results identify text, visual or both sources:

- Text matches show actual excerpts, PDF page numbers and source boxes where available. Semantic text matches explain when your phrase does not appear literally.
- Visual-only matches show the image without invented excerpts or text highlights. A textless image with a successful visual index is searchable.
- DOCX previews show body text and heading/paragraph/table references, without inferred page numbers or Word layout.
- **Download original** retrieves the untouched file as an attachment for your local viewer.

Ctrl+K focuses search, Enter searches, Tab navigates controls and Escape closes the preview. The layout supports narrow screens.

### Retry, cancel and reindex

Open a file to inspect its independent text and visual states. **Reindex visual** adds or rebuilds an image's visual index without another upload or replacing its text index. **Reindex text** rebuilds OCR/extracted-text indexing; PDF and DOCX support text reindexing only.

**Retry** retries failed processing. **Cancel processing** stops a queued/active attempt while retaining the original and useful existing indexes. Text and visual failures are independent: a working capability remains available when the other fails. New text extraction whose embeddings fail can still support keyword search.

Existing installations migrate additively to schema version 2. Originals, previews, chunks and indexes are preserved; old images are marked **visual: not_indexed** and need explicit visual reindexing. Startup does not silently reprocess the entire collection.

Replacing models can change their identity. Search skips incompatible vectors and explains that reindexing is needed; lexical text remains available. After model setup or replacement, restart the backend and retry/reindex affected files. Setup alone does not rebuild document indexes.

## Troubleshooting

| Problem | Supported next step |
| --- | --- |
| Missing models or a missing manifest | Stop the backend, run the relevant setup command from this project's directory with internet access, then restart. Retry failed files or explicitly reindex the affected capability. Check that setup and runtime use the same `RECALL_MODELS` directory if you configured one. |
| Damaged model files | Setup reuses embedding caches and does **not** request a forced redownload. Rerunning it is not a guaranteed corruption repair. Text setup overwrites bundled OCR files and checks a text embedding; visual setup loads the encoders and records fingerprints. Neither provides a complete cache-repair tool. If setup still fails, retain the error for diagnosis; arbitrary cache-corruption recovery has not been verified. Keep uploaded data in `.recall/` intact. |
| Port 8765 is occupied | If your Recall server is already running, open it. Otherwise stop the conflicting process if appropriate, or use the alternate-port command below. A second Recall process cannot share the same data directory, even on another port. |
| An upload is rejected | Check the [supported-content limits](#supported-content-and-limits). Export an actual supported format, unlock encrypted files, resize images or split large documents. Changing the filename extension does not convert the file. |
| A file shows failed processing | Read its error, fix the cause and choose **Retry**. A timeout may need a smaller/simpler source file. Repeatedly retrying the same malformed source will not repair it. |
| An existing image has no visual results | Open it and choose **Reindex visual**. Confirm visual model setup completed and the image's visual state becomes ready. Existing images are not automatically reindexed. |
| Search results are missing | Wait for processing to finish; inspect text/visual states and errors. Use the mode appropriate to the available capability. Insufficient OCR text limits Text search; a visual failure limits Visual search. Check model warnings and retry/reindex after addressing their cause. Similarity retrieval can also miss relevant items. |

To choose another port, after stopping any Recall process using this data directory:

```powershell
.venv/Scripts/python -m uvicorn backend.app:app --host 127.0.0.1 --port 8770
```

Then open **http://127.0.0.1:8770**. The optional `run.ps1` launcher always uses port 8765.

## Persistence and privacy

| Default path | Contents |
| --- | --- |
| `.recall/originals/` | Untouched uploaded bytes under stable IDs |
| `.recall/previews/` | Inert JPEG previews for images/PDF pages |
| `.recall/recall.sqlite3` | Metadata, persistent queue, extracted text, source references and text/visual indexes |
| `.recall/work/<job-id>/` | Temporary ownership metadata, preview images and intermediate text/vector JSON for a processing attempt |
| `.models/` | Downloaded model caches and manifests |

These data/model directories are ignored by Git and are not included in a normal clone or push to GitHub. Generated fixtures, test artifacts, dependencies and secrets are also ignored. **Local storage is not encrypted at rest**; Windows account permissions apply. Back up `.recall/` with the backend stopped. Recall does not manage backups.

Closing the browser tab leaves the backend running. Stopping/restarting the backend preserves uploaded documents and indexes; interrupted work resumes from the persistent queue. Cancelling a job keeps its original and previous useful indexes for an explicit retry.

Job staging is temporary, but an active attempt may still need it. Cleanup checks ownership/live workers, waits for child processes to exit, retries Windows sharing violations and defers locked folders. Startup requeues interrupted work and safely reconciles abandoned generated job folders; originals and persistent queue entries allow recovery without stale staging. Unknown paths, symlinks, junctions and live foreign owners are preserved. Startup does not sweep originals, previews or database records.

Deleting a document **through the app** stops its worker and removes its original, previews, known job staging, extracted text and both search indexes. A Windows sharing error asks for a retry. This is application deletion, not forensic erasure; external downloads and backups are outside Recall's control. SQLite secure-delete and WAL checkpointing reduce leftover database content.

Runtime uses explicit local OCR paths, `local_files_only=True` and offline Hugging Face settings. Offline inference was exercised with non-loopback Python socket connections blocked in the server and workers; this is a test guard, not an OS network sandbox.

## Supported content and limits

| Limit | Behavior |
| --- | --- |
| PNG, JPEG, PDF, DOCX | Validates actual content/package structure. DOC, DOCM, encrypted Office files and encrypted PDFs are unsupported. |
| 20 MiB per original | Export a smaller file if exceeded. |
| 10 files per HTTP batch | UI batches larger selections. Request cap: 200 MiB plus 1 MiB multipart overhead. |
| 1–20 PDF pages | Split larger PDFs. Embedded text is preferred; scanned pages receive OCR. |
| 25 megapixels per image | Resize larger images. OCR input has a maximum 2200-pixel long side. |
| DOCX: 1,000 ZIP entries / 50 MiB expanded | Checks archive paths, duplicates, encryption, macros and required package parts. Does not extract archives to disk. |
| DOCX: 8 MiB per XML/rels part / 200,000 body characters | Split oversized documents. External resources are not resolved; entities in parsed XML are rejected. |
| 500 source chunks per file | Split dense documents; DOCX chunks retain paragraph/table references. |
| 120 seconds per processing job | Includes worker/model startup, extraction and indexing. Timeout kills and waits for the worker; completed capabilities may remain available and unfinished work is retryable. |
| 300 characters per query / 30 results | CLIP has a 77-token text context; long visual descriptions may be truncated. |
| One processing worker | Persistent queue; expensive extraction/inference runs outside the request path. Search runs in the API thread pool. |

DOCX supports ordinary body paragraphs, built-in HeadingN references and top-level tables in document order. Word pagination, embedded-image OCR, headers/footers, text boxes, merged/nested-table layout and advanced content controls/custom heading styles are not fully supported. Embedded objects are never executed.

Visual indexing is limited to standalone PNG/JPEG images, not PDF pages or DOCX embedded images. PDFs with sufficient embedded text may miss text inside additional raster images on the same page. English printed OCR and short English visual descriptions are the initial target; handwriting and multilingual content have not been benchmarked.

`RECALL_DATA` and `RECALL_MODELS` select alternative local directories; use the same values consistently across setup and server runs. `RECALL_PROCESS_TIMEOUT` overrides the job budget for tests. Default paths are relative to the project, not the terminal's working directory.

## Hardware observations

No minimum RAM/CPU specification has been established. Measurements came from an **Intel64 Family 6 Model 61 CPU with four logical processors**, using two inference threads on the Windows configuration above.

| Observation | Recorded result |
| --- | --- |
| Model cache storage on disk | About **697 MiB** combined; separate from RAM and installed dependencies |
| Backend plus worker memory | **958.9 MiB** peak summed RSS, sampled every 0.2 seconds; shared pages may be counted twice and brief peaks missed |
| Ten-file synthetic collection | **53.313 seconds** total processing |
| Six-file visual/DOCX collection | **46.47 seconds** total; **2.902–11.441 seconds** per file including startup |
| Visual retrieval | **2.845 seconds** for first query; **0.035–0.052 seconds** for subsequent measured queries |
| All retrieval in the extension run | **0.421 seconds** on first use after Visual; **0.050–0.068 seconds** subsequently |

Query measurements exclude HTTP/browser overhead. These are observations on small fixtures, not hardware requirements, latency guarantees or general accuracy claims. Larger/noisier files may take longer or hit limits. See [detailed measurements and limitations](VERIFICATION.md#processing-time-query-latency-and-memory).

## Technical details

Recall uses FastAPI, SQLite, local ONNX inference and a React/TypeScript frontend bundled with esbuild. There is no hosted service or vector database. See [PROJECT_BRIEF.md](PROJECT_BRIEF.md) for scope and [AGENTS.md](AGENTS.md) for development conventions.

MiniLM produces 384-dimensional text vectors. The paired **Qdrant/clip-ViT-B-32-text** and **Qdrant/clip-ViT-B-32-vision** encoders produce 512-dimensional visual-query/image vectors. CLIP reuses FastEmbed/ONNX's CPU stack without adding PyTorch or a GPU; its vectors are stored separately and are never compared directly with MiniLM.

Manifests record model names, library versions and fingerprints; indexed vectors retain model identity. Visual setup records snapshot paths, sizes and SHA-256 hashes. Its runtime checks cache presence, sizes and version, without rehashing every file on each query.

Text ranking combines SQLite FTS5, literal phrase/name matches, token coverage and MiniLM similarity (initial semantic threshold **0.40**). Visual ranking uses paired CLIP vectors (initial threshold **0.23**). All uses reciprocal-rank fusion: sum **1 / (60 + rank)** across each document's separate rankings, deduplicate by stable ID, then prioritize exact phrase/filename evidence. Numeric-only All queries use Text only. Raw model similarities are never added across spaces or presented as confidence percentages.

| Module | Responsibility |
| --- | --- |
| `backend/storage.py` | IDs, hashes, persistent SQLite data and additive migration |
| `backend/processing.py`, `job_files.py`, `worker.py` | Queue, bounded subprocesses, atomic index commits and ownership-aware cleanup |
| `backend/extraction.py`, `docx.py` | PDF text, OCR, source boxes and bounded DOCX extraction |
| `backend/embeddings.py`, `visual.py` | Separate local text and visual encoders/manifests |
| `backend/retrieval.py` | Rankings, fusion and supporting-source explanations |
| `backend/app.py`, `frontend/` | Same-origin API and interface |

The API checks hosts/origins, requires a client header for mutations and sets a restrictive content-security policy. React treats filenames and extracted content as untrusted text; original downloads are attachments. Parsers run in a bounded subprocess, **not a hardened OS security sandbox**.

## Development and verification

After installing dependencies and setting up models:

```powershell
npm run build
.venv/Scripts/python -m pytest -q
.venv/Scripts/python -m scripts.fixtures
.venv/Scripts/python -m scripts.verify
npm run test:browser
.venv/Scripts/python -m scripts.extension_fixtures
.venv/Scripts/python -m scripts.verify_extensions
npm run test:browser:extensions
```

The extension fixture command explicitly downloads four public test photos if absent and generates a synthetic DOCX. Run it before extension checks; inference itself stays offline. These photos are test assets, not the synthetic in-app demo. Source URLs are recorded in `scripts/extension_fixtures.py` and generated `sources.json`; the assets are ignored by Git.

The build includes strict TypeScript checking. `npm run watch` rebuilds frontend assets; refresh the browser afterward. Restart the backend for Python changes.

Tests launch isolated servers/databases under ignored `artifacts/` and stop them afterward. Keep ports **8766–8769** free. Browser scripts use installed **Microsoft Edge** through Playwright.

| Check | Generated report |
| --- | --- |
| Ten-file HTTP/retrieval/restart/retry suite | `artifacts/verification.json` |
| Existing browser journey | `artifacts/browser-verification.json` |
| Visual/DOCX/offline/crash/cleanup suite | `artifacts/extensions-verification.json` |
| Visual/DOCX browser journey | `artifacts/browser-extensions-verification.json` |

[VERIFICATION.md](VERIFICATION.md) records the tested build, 16 backend tests, both integration suites and both browser journeys. Recorded retrieval ranked the expected file first for 12/12 text queries and 4/4 visual queries per mode, with an irrelevant secondary visual result. These small authored collections do not establish general accuracy. Large collections, long-running memory, other browsers/OS versions, screen-reader behavior and a malicious-file security audit remain unverified.

## Licensing and dependency references

**No project LICENSE file is included.** The owner still needs to choose and add a project license. Dependency/model licenses below do not license Recall itself.

PyMuPDF is distributed under AGPL/commercial terms; review its license before distributing a derivative product. The paired CLIP encoders are listed as MIT in their [text model repository](https://huggingface.co/Qdrant/clip-ViT-B-32-text) and [vision model repository](https://huggingface.co/Qdrant/clip-ViT-B-32-vision). Other software, model and test-image licenses remain with their respective projects.

Implementation references: [FastAPI uploads](https://fastapi.tiangolo.com/tutorial/request-files/), [FastEmbed supported models](https://qdrant.github.io/fastembed/examples/Supported_Models/), [FastEmbed package](https://pypi.org/project/fastembed/), [RapidOCR installation](https://rapidai.github.io/RapidOCRDocs/main/en/install_usage/rapidocr/install/) and [esbuild](https://esbuild.github.io/getting-started/). esbuild supports the tested Node configuration without changing Node. DOCX parsing uses Python ZIP support and defusedxml; process tracking uses psutil.

[requirements.lock.txt](requirements.lock.txt) and [package-lock.json](package-lock.json) record tested dependencies; [requirements.txt](requirements.txt) describes direct dependency ranges.
