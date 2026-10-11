# Recall verification — 11 October 2026

Verified on Windows 10 x64, Python 3.13.0, Node 20.18.0, npm 10.8.2 and headless Microsoft Edge. CPU: Intel64 Family 6 Model 61, four logical processors. Inference used ONNX Runtime's CPU provider with two threads. No GPU or external AI service was used.

## Checks run

| Command | Actual result |
| --- | --- |
| `npm run build` | Passed strict TypeScript checks and production bundle |
| `.venv/Scripts/python -m pytest -q` | **16 passed** |
| `.venv/Scripts/python -m scripts.verify` | Existing HTTP/retrieval/restart/retry checks passed; **12/12 expected first results** |
| `npm run test:browser` | **19 checks passed**, no JavaScript exceptions |
| `.venv/Scripts/python -m scripts.verify_extensions` | **30 checks passed**, real local CLIP/MiniLM/OCR inference |
| `npm run test:browser:extensions` | **10 checks passed**, no JavaScript exceptions |

The final backend tests also cover preserving existing text vectors when a text reindex reaches extraction but embedding fails, cleanup path validation, deleting older deferred attempts, and DOCX entity/XML-size rejection. These targeted tests ran after the integration/browser suites. No frontend behavior changed afterward.

## Existing ten-file retrieval

The existing fixture collection contains ten synthetic files: six PNG/JPEG images and four PDFs, including a scanned page, a two-page PDF and an image without readable text. A separate duplicate attempt yields the same stable ID and ten stored documents. All ten completed processing, including the textless image with its warning.

Actual results from `artifacts/verification.json`:

| Query | Actual first file | Page | Match | Expected rank |
| --- | --- | ---: | --- | ---: |
| headphone receipt | IMG_4821.png | 1 | Keyword match | 1 |
| 89.99 | IMG_4821.png | 1 | Exact phrase | 1 |
| proof I paid for wireless audio gear | IMG_4821.png | 1 | Semantic match | 1 |
| Maya Chen | scan_023.pdf | 1 | Exact phrase | 1 |
| cancellation policy | download_7.pdf | 2 | Exact phrase | 1 |
| instructions for keeping my houseplants alive | Screenshot_108.png | 1 | Semantic match | 1 |
| train to Bristol | ticket_09.jpg | 1 | Exact phrase | 1 |
| roasted tomato soup | image_110.jpeg | 1 | Exact phrase | 1 |
| internet bill | document_12.pdf | 1 | Exact phrase | 1 |
| appointment with the dentist | Screenshot_201.png | 1 | Semantic match | 1 |
| library books due date | note_62.pdf | 1 | Keyword match | 1 |
| IMG_4821.png | IMG_4821.png | 1 | Filename | 1 |

All twelve expected files ranked first in the original labelled collection, and the unrelated negative query returned no results. This is a small authored fixture set, not an independent accuracy benchmark.

## Visual retrieval with distractors

Four public test photos use neutral filenames and compete with each other, a synthetic DOCX and a receipt. These photos are test-only assets downloaded explicitly; the in-app demo remains clearly synthetic. Sources are recorded in `scripts/extension_fixtures.py`.

Actual paired-encoder results from `artifacts/extensions-verification.json`:

| Query | Intended image | Visual rank | All rank | Other returned result |
| --- | --- | ---: | ---: | --- |
| a dog playing outside | IMG_4821.jpg | 1 | 1 | None |
| two cats resting on a couch | IMG_5932.jpg | 1 | 1 | None |
| a bus parked on a city street | IMG_6104.jpg | 1 | 1 | None |
| two men wearing ties | IMG_7785.jpg | 1 | 1 | **IMG_5932.jpg, rank 2: false positive** |

**4/4 intended top results in each mode**, with one irrelevant secondary result. The dog is visibly sitting on grass; “playing” is a related query, not a verified action. CLIP retrieves related image content and cannot establish all details in a sentence. No caption, excerpt, probability or text highlight is invented for these visual results. The dog image has insufficient OCR text and remains visually searchable.

## DOCX and failure behavior

- Ordered paragraphs and table cells retain heading/paragraph/table references. The fixture's “Nora Bennett” paragraph and exact **127.45** table amount are retrievable.
- Original DOCX downloads match uploaded bytes. The browser shows references and actual body text, no invented pages; literal HTML-like text remains inert.
- Unit checks reject malformed ZIPs, macro packages, unsafe paths, excess entries, expanded-size overflow, oversized XML and entities in parsed XML.
- Existing OCR receipt search for **89.99** remains useful alongside visual search.
- Missing CLIP models leave new receipt text search ready and show a visual capability error. Restoring model configuration and retrying builds the missing visual index.
- Explicit visual reindex preserves existing text chunks. A failed text embedding reindex preserves previous useful text and visual indexes.
- Visual index and DOCX persistence, original downloads, retries and deletion were checked through the real API. Unit tests check cascading vector deletion.
- An active worker was confirmed before forcibly killing the backend; the child exited, the persistent job recovered after restart, and search still worked.
- Staging was empty after success, processing failure, cancellation, timeout and interrupted-job recovery. A one-second reindex timeout preserved a previous useful index.
- A simulated Windows sharing violation succeeds after retries; unknown directories and folders owned by another live process remain untouched. Path validation precedes any worker termination.

The integration server and its workers ran with Python non-loopback socket connections blocked, successfully processing and searching all fixtures. This verifies the exercised inference paths use local caches; it is not a whole-system packet capture.

## Processing time, query latency and memory

Times below are wall-clock observations on this CPU, including per-document process/model startup. They are not latency guarantees.

The original ten-file collection took **53.313 seconds**. First All search took **2.118 seconds**, subsequent descriptive searches approximately **0.034–0.045 seconds**, and the exact-amount query **0.011 seconds**.

The six-file extension collection took **46.47 seconds**:

| File | Processing seconds |
| --- | ---: |
| IMG_4821.jpg — dog | 8.645 |
| IMG_5932.jpg — cats | 5.462 |
| IMG_6104.jpg — bus | 6.860 |
| IMG_7785.jpg — people | 10.079 |
| download_42.docx | 2.902 |
| receipt.png | 11.441 |

First Visual query took **2.845 seconds**, including loading the CLIP text encoder. The first All query afterward took **0.421 seconds**, including first text-search model use. Subsequent Visual queries took **0.035–0.052 seconds**; All queries took **0.050–0.068 seconds**. These are retrieval-function timings; HTTP/browser overhead is additional.

The paired CLIP cache measured **579.85 MiB**, in addition to about **117 MiB** for the existing text/OCR cache. The sampled backend-plus-descendant peak RSS was **958.9 MiB**, sampled every 0.2 seconds during the extension suite. Summed process RSS may double-count shared memory and miss short peaks; this is not private-memory accounting or a long-running stress test.

## Migration and existing data

An additive legacy-schema unit test runs migration twice and checks preservation without silently queuing old images for visual indexing.

The actual default collection was then checked under its server lock. Its **3 documents, 3 chunks and 6 original/preview files** were preserved across migration to schema version 2. Original/preview byte hashes and existing metadata, chunk text, source boxes, vectors and model IDs matched before and after. All documents remained ready, with no automatic jobs queued. The default work directory contained zero entries.

Only structural/equality checks were performed on personal data; no personal contents or filenames were copied into reports, retrieval fixtures or an external service. Evidence is in ignored `artifacts/existing-data-migration.json`.

## Browser and regression coverage

The existing browser journey covered multi-upload, Ctrl+K, exact and paraphrased search, semantic explanation, source highlights, original download, Escape, PDF navigation, duplicate feedback, failure/retry, no-results, deletion/reload, image filtering, labelled demo loading and mobile layout.

The extension browser journey covered image/DOCX uploads, mode switching, textless image retrieval, visual preview without text evidence, explicit reindex/cancel, DOCX table references and safe text preview, original download, DOCX filtering, malformed archive feedback and a 390-pixel viewport without horizontal overflow. Visual, DOCX and mobile screenshots were also inspected.

Existing HTTP checks retained traversal-looking names as metadata only, rejected fake image HTML, rejected cross-origin/missing-header mutations, and checked restart, deletion, missing models and real timeouts. Git ignore checks covered user data, models, secrets, fixtures and artifacts.

Reports and screenshots live under ignored `artifacts/`. Tests use separate databases and shut down their servers. No public deployment, commit or push was performed.

## What remains unverified or limited

This is a small demonstration, not broad retrieval accuracy evidence. Visual search returned a false positive; its initial threshold can miss relevant images or return unrelated ones. Fine-grained actions/counting, long descriptions, multilingual queries, real photo-library scale and handwritten OCR were not benchmarked. CLIP's text context is limited to 77 tokens.

DOCX headers/footers, text boxes, embedded-image OCR, Word pagination, nested/merged-table layout and advanced/custom-style handling remain unsupported. Visual search does not index PDF pages or DOCX embedded images. PDFs with enough embedded text may miss text inside additional raster images on the same page.

Only this Windows/Edge environment was tested. Screen-reader behavior, other browsers/OS versions, long-running memory, disk-full recovery, machine power loss and a malicious-file security audit remain unverified. Parser subprocesses are not an OS sandbox. Forced backend crashes and Windows sharing errors were exercised; that does not cover every filesystem failure. Deletion does not promise forensic erasure or remove external backups/downloads.
