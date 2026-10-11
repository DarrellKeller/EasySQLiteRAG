from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile

import pytest

pytest.importorskip('markitdown')
from local_rag.extract import ExtractionReport, convert_documents, main


def test_real_markdown_html_and_spreadsheet_conversion(tmp_path):
    from openpyxl import Workbook
    source=tmp_path/'documents';source.mkdir()
    (source/'notes.md').write_text('# Heading\n\nEvidence with a [link](https://example.com).',encoding='utf-8')
    (source/'page.html').write_text('<h1>Section</h1><table><tr><th>Item</th><th>Value</th></tr><tr><td>Count</td><td>7</td></tr></table>')
    book=Workbook();sheet=book.active;sheet.title='Records'
    sheet.append(['Item','Value']);sheet.append(['Count',7]);book.save(source/'records.xlsx')
    output=tmp_path/'extracted'
    report=convert_documents(source,output)
    assert all(record.status=='extracted' for record in report.records)
    by_name={record.relative_path:record for record in report.records}
    assert '# Heading' in (output/by_name['notes.md'].markdown_path).read_text()
    assert 'Section' in (output/by_name['page.html'].markdown_path).read_text()
    sheet_text=(output/by_name['records.xlsx'].markdown_path).read_text()
    assert 'Count' in sheet_text and '7' in sheet_text and 'Records' in sheet_text
    assert by_name['records.xlsx'].issues[0].kind=='structured_data_review'
    loaded=ExtractionReport.model_validate_json((output/'manifest.json').read_text())
    assert loaded==report and loaded.converter_version


def test_real_word_conversion(tmp_path):
    source=tmp_path/'document.docx'
    with ZipFile(source,'w') as archive:
        archive.writestr('[Content_Types].xml','<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        archive.writestr('_rels/.rels','<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Actual Word evidence</w:t></w:r></w:p></w:body></w:document>')
    output=tmp_path/'extracted';report=convert_documents(source,output)
    assert report.records[0].status=='extracted'
    assert 'Actual Word evidence' in (output/report.records[0].markdown_path).read_text()


def test_real_pdf_conversion_requires_page_review(tmp_path):
    # Minimal PDF constructed in a temporary directory; never shipped as data.
    objects=[b'<< /Type /Catalog /Pages 2 0 R >>',
             b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
             b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
             b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    stream=b'BT /F1 12 Tf 72 720 Td (PDF source evidence) Tj ET'
    objects.append(b'<< /Length '+str(len(stream)).encode()+b' >>\nstream\n'+stream+b'\nendstream')
    data=b'%PDF-1.4\n';offsets=[]
    for i,obj in enumerate(objects,1):
        offsets.append(len(data));data+=f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n'
    xref=len(data);data+=b'xref\n0 6\n0000000000 65535 f \n'
    data+=b''.join(f'{offset:010d} 00000 n \n'.encode() for offset in offsets)
    data+=f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF'.encode()
    source=tmp_path/'document.pdf';source.write_bytes(data)
    output=tmp_path/'extracted';record=convert_documents(source,output).records[0]
    assert record.status=='extracted'
    assert 'PDF source evidence' in (output/record.markdown_path).read_text()
    assert any(issue.kind=='pdf_review' for issue in record.issues)


def test_batch_reports_failed_empty_unsupported_and_symlink_inputs(tmp_path):
    source=tmp_path/'documents';source.mkdir();output=tmp_path/'extracted'
    for name in ['good.md','empty.md','broken.pdf','opaque.bin']:(source/name).write_text('original')
    (source/'linked.md').symlink_to(source/'good.md')
    class Converter:
        def convert_local(self,path):
            if Path(path).name=='broken.pdf':raise ValueError('Cannot read PDF')
            return SimpleNamespace(text_content='Evidence' if Path(path).name=='good.md' else ' ')
    report=convert_documents(source,output,converter=Converter())
    statuses={record.relative_path:record.status for record in report.records}
    assert statuses=={'broken.pdf':'failed','empty.md':'empty','good.md':'extracted','linked.md':'skipped','opaque.bin':'unsupported'}
    assert len(list(output.glob('*.md')))==1
    assert all(record.issues for record in report.records if record.status!='extracted')
    assert (source/'good.md').read_text()=='original'


def test_repeatable_ids_changed_hashes_and_output_exclusion(tmp_path):
    source=tmp_path/'documents';source.mkdir();output=source/'extracted'
    (source/'nested').mkdir();file=source/'nested/source.md';file.write_text('First evidence')
    assert convert_documents(source,output).records==[]
    first=convert_documents(source,output,recursive=True).records[0]
    file.write_text('Updated evidence')
    second=convert_documents(source,output,recursive=True).records[0]
    assert first.id==second.id and first.markdown_path==second.markdown_path
    assert first.source_sha256!=second.source_sha256
    assert len(list(output.glob('*.md')))==1
    assert (output/second.markdown_path).read_text()=='Updated evidence'
    with pytest.raises(ValueError):convert_documents(source,source)
    with pytest.raises(ValueError):convert_documents(tmp_path/'missing',output)


def test_source_modified_during_conversion_is_not_exported(tmp_path):
    file=tmp_path/'source.md';file.write_text('Before')
    class Converter:
        def convert_local(self,path):
            Path(path).write_text('After')
            return SimpleNamespace(text_content='Before')
    output=tmp_path/'extracted';record=convert_documents(file,output,converter=Converter()).records[0]
    assert record.status=='failed' and 'Source changed' in record.issues[0].message
    assert record.markdown_path is None and not list(output.glob('*.md'))


def test_cli_exit_status_reports_partial_or_empty_batches(tmp_path):
    file=tmp_path/'source.md';file.write_text('Evidence')
    assert main([str(file),'--output',str(tmp_path/'out')])==0
    file.write_text('')
    assert main([str(file),'--output',str(tmp_path/'out')])==1
    empty=tmp_path/'empty';empty.mkdir()
    assert main([str(empty),'--output',str(tmp_path/'out')])==1
