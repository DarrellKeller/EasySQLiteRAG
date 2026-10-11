# MarkItDown extraction

Use the repo's `local_rag.extract` command for selected local documents. It provides the reusable conversion stage; the coordinating agent still designs hierarchy, chunks, ingestion writes, embeddings and the map. Do not replace the provided UI or index every workspace file.

## Install and run

Install the optional document dependencies in the project's environment:

```sh
.venv/bin/python -m pip install -e './backend[documents]'
.venv/bin/python -m local_rag.extract documents --recursive
```

The positional argument can be a single file or a selected folder elsewhere. Quote paths containing spaces. On Windows use `.venv\Scripts\python.exe` instead. `--recursive` includes nested folders; `--output` selects a separate output directory. The default is Git-ignored `data/extracted/`. Inspect the actual selected sources before running; never use starter code as the dataset.

Document dependencies include local PDF, Word, PowerPoint and Excel support. The command also accepts text/Markdown, HTML, CSV, JSON, XML and YAML. It configures no cloud model, Azure service or third-party plugin. These conversions do not require an API key. Additional OCR or cloud recovery needs separate, explicit configuration appropriate to the user's choices.

## What the output means

Each source has a stable path-derived ID, original path, relative folder path, source SHA-256, extraction status and issue list in `manifest.json`. Successful conversions produce an ID-named Markdown file, with output hash and character count. Sources are preserved; text is not capped or deliberately truncated by this command. Files that fail, return empty text, are unsupported or are symlinks are reported individually while unaffected files continue. Hidden files and dependency/build folders are excluded. Select symlink targets explicitly if wanted.

Rerunning refreshes the manifest for the current selection and overwrites successful exports by stable ID. Only read exports referenced by the **current manifest** with `status=extracted`; old Markdown files can remain after a source disappears or a later conversion fails. Do not glob every old output file into the index. Compare hashes to reuse unchanged downstream chunks/embeddings and remove stale indexed records only after confirming the intended source set.

Exit 0 means all selected files returned nonempty text, **not** that completeness was verified. Exit 1 means an empty selection or at least one unresolved extraction/skipped/unsupported record; exit 2 means invalid setup/path/options. Inspect the manifest and questions, not just the exit code.

## Review before ingestion

Use relative paths and extracted headings to propose an evidence-grounded hierarchy. Inspect originals alongside Markdown. MarkItDown conversion is not a complete coverage audit:

- PDFs always carry a review note: inspect pages, reading order, tables, scanned/sparse pages and page citations. Use a page-aware parser to add accurate page anchors; do not infer page numbers from Markdown line numbers. Ordinary conversion is not proof that OCR ran or that every page was extracted.
- Spreadsheets, CSV and JSON carry a review note: use their original structured representation to verify sheets/rows, field types, formulas, relationships, oversized-cell placeholders and intentional blanks. Markdown tables alone are insufficient to verify these.
- Word/PowerPoint/HTML also need representative structure/content checks and meaningful source anchors. Flag extraction omissions as evidence emerges.
- Replacement characters trigger an encoding question. Failed and empty conversions need an actual recovery decision; never embed invented replacements or silently omit them.

Distinguish **review required** from **confirmed missing content**. Bring grouped failures and actual gaps to the user throughout processing. Transfer unresolved issues and concrete original locators into SQLite's `ingestion_issues` register, attached to the corresponding real hierarchy nodes, so the provided Data issues panel and source coverage notes expose them. The extraction command writes an intermediate manifest; it does not automatically populate that database register or imply issues are resolved. Keep review notes until checked, then record the evidence and resolution.

After review, implement/run the dataset-specific ingestion using real extracted text and original structured data where appropriate, preserve citations, exclude unavailable text, validate coverage, and generate embeddings/map coordinates as instructed by the skill.

[Microsoft MarkItDown](https://github.com/microsoft/markitdown) is MIT-licensed. Its converter preserves useful Markdown structure where possible; fidelity and extraction coverage still require verification.
