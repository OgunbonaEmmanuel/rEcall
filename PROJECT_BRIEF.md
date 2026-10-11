# Recall — agreed MVP

Everyday users can upload poorly named screenshots and documents, then find them by exact text or a description of remembered content. Milestone: process ten synthetic mixed image/PDF files and report actual labelled retrieval results.

## Scope

- Multiple PNG, JPEG, PDF and DOCX ingestion, stable IDs, original names, SHA-256 deduplication, queued/processing/ready/failed states, retries and complete deletion.
- Embedded PDF text and local OCR for images/scanned pages. Retain page numbers and normalized bounding boxes. DOCX body paragraphs/tables retain source references without invented pagination. Standalone images also receive local CLIP visual indexes, including textless images.
- Keyword plus MiniLM text retrieval, independent paired CLIP image/text retrieval, and All/Text/Visual modes. All uses reciprocal-rank fusion with exact-evidence priority. Identify text, visual or both sources; visual-only matches have no text excerpts or highlights. No generated answers or probability claims.
- Responsive, keyboard-accessible upload/search/preview/delete UI and clearly labelled synthetic demo collection.
- Local single-user disk + SQLite persistence. CPU only. Explicit initial model download, no external AI fallback, no public deployment or authentication.

## Architecture and stages

1. FastAPI ingestion, SQLite metadata, originals on disk, isolated background extraction workers with hard time limits.
2. SQLite FTS5 keywords plus FastEmbed ONNX text vectors, persisted per source chunk and model fingerprint. Ten labelled synthetic fixtures.
3. React/TypeScript interface bundled with esbuild; FastAPI serves the built frontend on loopback.
4. Unit/integration tests, actual restart/delete/retry checks, browser journey and measured CPU timings.

## Initial limits

20 MiB per file; 10 files per request; 20 PDF pages; 25 megapixels per image; 120 seconds of processing per document; 500 source chunks per document; 300-character search query; one processing worker. Local collection target: hundreds of files, not millions. English printed text is the initial OCR/search target.

## Out of scope

Chat, invented answers, reminders, Life Admin, automatic scanning, OCR of DOCX embedded images, visual indexing of PDF pages or DOCX embedded images, handwriting guarantees, encrypted PDFs/Office files, shared accounts, authentication, cloud storage, external inference, public hosting.

## Authorized extension — October 2026

Add offline CPU CLIP visual retrieval for standalone PNG/JPEG uploads, bounded DOCX ingestion/extraction, independently retryable text/visual indexes, explicit reindexing of existing files, additive schema migration, and crash-safe temporary-job cleanup. Preserve existing originals, previews and database content. DOCX limits: 1,000 ZIP entries, 50 MiB expanded, 8 MiB per XML/rels part, 200,000 body characters, plus existing 500 chunks/120 seconds. Test real image retrieval with neutral filenames/distractors, DOCX source evidence, missing models, partial failures, crash recovery, cleanup, migration, restart and deletion. No commit or push requested.
