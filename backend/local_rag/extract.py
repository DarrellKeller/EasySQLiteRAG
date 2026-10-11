"""Local document conversion; hierarchy/chunking/indexing remain agent-designed."""
import argparse
import hashlib
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from pydantic import Field

from .models import StrictModel
from .settings import ROOT

SUPPORTED = {'.pdf', '.docx', '.pptx', '.xlsx', '.xls', '.txt', '.md', '.mdx',
             '.html', '.htm', '.csv', '.json', '.xml', '.yaml', '.yml'}
EXCLUDED = {'.git', '.venv', 'node_modules', 'dist', '__pycache__'}


class ExtractionIssue(StrictModel):
    kind: str
    message: str
    question: str


class ExtractionRecord(StrictModel):
    id: str
    source_path: str
    relative_path: str
    source_sha256: str | None = None
    status: Literal['extracted', 'empty', 'failed', 'unsupported', 'skipped']
    markdown_path: str | None = None
    markdown_sha256: str | None = None
    character_count: int = Field(default=0, ge=0)
    issues: list[ExtractionIssue] = Field(default_factory=list)


class ExtractionReport(StrictModel):
    source_root: str
    converter: str
    converter_version: str
    records: list[ExtractionRecord]


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(block)
    return hasher.hexdigest()


def write_atomic(path: Path, text: str):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def convert_documents(source: Path, output: Path, recursive: bool = False,
                      converter=None) -> ExtractionReport:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    if not source.exists():
        raise ValueError(f'Data path does not exist: {source}')
    if source == ROOT:
        raise ValueError('Select your data folder or file, rather than the starter repo.')
    if output == source or source.is_relative_to(output):
        raise ValueError('Use a separate output folder; it must not contain the source.')
    if converter is None:
        try:
            from markitdown import MarkItDown
        except ImportError:
            raise ValueError("Install document support: python -m pip install -e './backend[documents]'") from None
        # Local files only; no cloud clients or automatic plugins configured.
        converter = MarkItDown(enable_plugins=False)
    converter_version = version('markitdown')
    root = source if source.is_dir() else source.parent
    paths = (source.rglob('*') if recursive else source.glob('*')) if source.is_dir() else [source]
    selected = []
    for path in paths:
        relative = path.relative_to(root)
        if any(part.startswith('.') or part in EXCLUDED for part in relative.parts):
            continue
        if path.is_relative_to(output):
            continue
        if path.is_file() or path.is_symlink():
            selected.append(path)
    output.mkdir(parents=True, exist_ok=True)
    records = []
    for path in sorted(selected):
        record = ExtractionRecord(
            id=hashlib.sha256(str(path).encode()).hexdigest()[:24],
            source_path=str(path), relative_path=str(path.relative_to(root)),
            status='failed',
        )
        records.append(record)
        if path.is_symlink():
            record.status = 'skipped'
            record.issues.append(ExtractionIssue(kind='symlink', message='Symlink was not followed.', question='Should its target be included explicitly?'))
            continue
        if path.suffix.lower() not in SUPPORTED:
            record.status = 'unsupported'
            record.issues.append(ExtractionIssue(kind='unsupported_format', message=f'No configured converter for {path.suffix or "extensionless file"}.', question='Can you provide a readable export, or should the agent add a suitable parser?'))
            continue
        try:
            record.source_sha256 = digest(path)
            result = converter.convert_local(str(path))
            text = result.text_content
            if not isinstance(text, str):
                raise ValueError('Converter returned no text string.')
            if digest(path) != record.source_sha256:
                raise ValueError('Source changed during conversion; rerun after the file is saved.')
            record.character_count = len(text)
            if not text.strip():
                record.status = 'empty'
                record.issues.append(ExtractionIssue(kind='empty_text', message='Conversion returned no readable text; nothing was exported.', question='Is this intentionally empty, or is OCR/a readable export needed?'))
                continue
            filename = f'{record.id}.md'
            write_atomic(output / filename, text)
            record.markdown_path = filename
            record.markdown_sha256 = hashlib.sha256(text.encode('utf-8')).hexdigest()
            record.status = 'extracted'
            if path.suffix.lower() == '.pdf':
                record.issues.append(ExtractionIssue(kind='pdf_review', message='Markdown conversion alone does not verify every page, reading order or page citations.', question='Check page coverage and anchors against the original; do scanned or sparse pages need OCR?'))
            if path.suffix.lower() in {'.xlsx', '.xls', '.csv', '.json'}:
                record.issues.append(ExtractionIssue(kind='structured_data_review', message='Converted text does not verify sheet/row counts, field types, formulas, relationships or missing values.', question='Inspect the original structured data before designing hierarchy and chunks; are any gaps intentional?'))
            if '\ufffd' in text:
                record.issues.append(ExtractionIssue(kind='replacement_characters', message='Extracted text contains Unicode replacement characters.', question='Check source encoding and compare affected text with the original.'))
        except Exception as error:
            record.status = 'failed'
            record.issues.append(ExtractionIssue(kind='conversion_failed', message=f'{type(error).__name__}: {error}', question='Can this file be repaired, unlocked, converted another way, or retained as an unresolved gap?'))
    report = ExtractionReport(source_root=str(source), converter='MarkItDown',
                              converter_version=converter_version, records=records)
    write_atomic(output / 'manifest.json', report.model_dump_json(indent=2))
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description='Convert selected local documents to Markdown with a source/issue manifest. Does not index or embed.')
    parser.add_argument('source', type=Path, help='Selected data file or folder')
    parser.add_argument('--recursive', action='store_true', help='Include nested folders')
    parser.add_argument('--output', type=Path, default=ROOT / 'data/extracted')
    args = parser.parse_args(argv)
    try:
        report = convert_documents(args.source, args.output, args.recursive)
    except (ValueError, OSError) as error:
        parser.exit(2, f'{error}\n')
    if not report.records:
        print('No input files found. Check the data path and --recursive.')
        return 1
    for record in report.records:
        print(f'{record.status}: {record.relative_path} ({record.character_count:,} characters)')
        for issue in record.issues:
            print(f'  {issue.kind}: {issue.message} {issue.question}')
    print(f'Manifest: {args.output.expanduser().resolve() / "manifest.json"}')
    print('Extraction only. Review the manifest and originals before chunking/indexing.')
    return 1 if any(r.status != 'extracted' for r in report.records) else 0


if __name__ == '__main__':
    raise SystemExit(main())
