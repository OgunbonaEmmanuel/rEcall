# Recall development

Build a local, single-user text and visual search app for PNG/JPEG images, PDF and DOCX documents. Visual search and DOCX were explicitly authorized in October 2026. Read PROJECT_BRIEF.md before changing scope. Never add hosted processing, authentication, chat, reminders, device scanning, or deployment without a new request.

Keep ingestion/storage, extraction, embedding/indexing, retrieval, and UI separate. Use stable IDs for filesystem paths; preserve original names only as metadata. All extracted text is untrusted. Never execute originals or render their contents as HTML. Maintain page numbers, bounding boxes, model identity, and atomic indexing. Failures must be visible and retryable.

Use the paired CLIP image/text encoders only in their own space; never compare CLIP vectors to MiniLM. Track text and visual states independently and preserve useful indexes when reindexing fails. DOCX has paragraph/table references, not inferred page numbers or PDF boxes. Validate bounded ZIP/XML content; never execute embedded content or resolve external resources. Cleanup must check job ownership and live workers, wait for Windows handles, and preserve persistent originals, previews, indexes and recoverable queue entries. Schema migrations are additive; reindexing existing files is explicit.

Use CPU-only local inference. Model setup may download public model files; app runtime must use local files only. Never send document contents to an external provider. Ignore uploads, databases, models, secrets, generated fixtures and test artifacts in Git.

Verification: run `npm run build`, `.venv/Scripts/python -m pytest`, and the integration/browser scripts described in README.md. Measure real retrieval and processing results; do not imply perfect accuracy. Keep setup commands and verification limitations current. Do not introduce tests that merely mirror trivial presentation code.
