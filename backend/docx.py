"""Bounded OPC/DOCX reader. Reads ZIP members in memory; never extracts or resolves links."""
import io
import re
import stat
import zipfile
from pathlib import PurePosixPath
from defusedxml import ElementTree as ET

MAX_ENTRIES = 1000
MAX_EXPANDED = 50 * 1024 * 1024
MAX_XML = 8 * 1024 * 1024
MAX_TEXT = 200_000
W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
CT = '{http://schemas.openxmlformats.org/package/2006/content-types}'
R = '{http://schemas.openxmlformats.org/package/2006/relationships}'
DOC_TYPE = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml'

def package(content):
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
        entries = archive.infolist()
        if len(entries) > MAX_ENTRIES or sum(i.file_size for i in entries) > MAX_EXPANDED:
            raise ValueError('DOCX exceeds 1,000 ZIP entries or 50 MiB decompressed. Export a smaller DOCX.')
        names = set()
        for item in entries:
            path = PurePosixPath(item.filename)
            if (item.filename in names or path.is_absolute() or '..' in path.parts or '\\' in item.filename
                or ':' in item.filename or stat.S_ISLNK(item.external_attr >> 16)):
                raise ValueError('Unsafe or duplicate archive path in DOCX. Export a fresh DOCX.')
            names.add(item.filename)
            if item.filename.lower().endswith(('.xml','.rels')) and item.file_size > MAX_XML:
                raise ValueError('DOCX XML part exceeds 8 MiB. Split this document.')
            if item.flag_bits & 1:
                raise ValueError('Encrypted DOCX is unsupported. Upload an unlocked DOCX.')
            if item.filename.lower().endswith('vbaproject.bin'):
                raise ValueError('Macro-enabled DOCM is unsupported. Save as a macro-free DOCX.')
        required = {'[Content_Types].xml', '_rels/.rels', 'word/document.xml'}
        if not required <= names:
            raise ValueError('Not a DOCX package: required document parts are missing. Save as DOCX and try again.')
        for name in required:
            if archive.getinfo(name).file_size > MAX_XML:
                raise ValueError('DOCX XML part exceeds 8 MiB. Split this document.')
        types = ET.fromstring(archive.read('[Content_Types].xml'))
        if types.tag != CT+'Types' or any('macroEnabled' in e.get('ContentType','') for e in types):
            raise ValueError('Unsupported macro-enabled or malformed DOCX content types.')
        if not any(e.get('PartName') == '/word/document.xml' and e.get('ContentType') == DOC_TYPE for e in types):
            raise ValueError('Invalid DOCX main document content type. Export a fresh DOCX.')
        rels = ET.fromstring(archive.read('_rels/.rels'))
        if rels.tag != R+'Relationships' or not any(
            e.get('Type','').endswith('/officeDocument') and e.get('Target','').lstrip('/') == 'word/document.xml'
            and e.get('TargetMode') != 'External' for e in rels):
            raise ValueError('DOCX main-document relationship is missing or external.')
        root = ET.fromstring(archive.read('word/document.xml'))
        if root.tag != W+'document' or root.find(W+'body') is None:
            raise ValueError('DOCX body is malformed. Export a fresh DOCX.')
        return archive, root
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError('Malformed DOCX archive/XML. Export a fresh, unlocked DOCX.') from exc

def validate(content):
    archive, _ = package(content)
    archive.close()

def paragraph_text(node):
    if node.tag in {W+x for x in ['drawing','pict','object','txbxContent','del','instrText']}:
        return ''
    if node.tag == W+'t': return node.text or ''
    if node.tag == W+'tab': return '\t'
    if node.tag in {W+'br',W+'cr'}: return '\n'
    return ''.join(paragraph_text(child) for child in node)

def extract(path):
    archive, root = package(path.read_bytes())
    try:
        # Bounded streaming validates actual expanded sizes/CRC, including unconsumed parts.
        expanded = 0
        for item in archive.infolist():
            with archive.open(item) as stream:
                while block := stream.read(65536):
                    expanded += len(block)
                    if expanded > MAX_EXPANDED:
                        raise ValueError('DOCX exceeds 50 MiB decompressed. Split the document.')
    finally:
        archive.close()
    chunks, count, paragraph, table, heading = [], 0, 0, 0, ''
    def add(text, reference):
        nonlocal count
        count += len(text)
        if count > MAX_TEXT:
            raise ValueError('DOCX exceeds 200,000 extracted characters. Split the document.')
        for offset in range(0, len(text), 650):
            if text[offset:offset+650].strip():
                chunks.append({'page':0,'text':text[offset:offset+650], 'boxes':[], 'method':'DOCX text',
                               'reference':reference, 'heading':heading})
        if len(chunks) > 500:
            raise ValueError('DOCX exceeds 500 source chunks. Split the document.')
    for block in root.find(W+'body'):
        if block.tag == W+'p':
            paragraph += 1
            text = paragraph_text(block).strip()
            style = block.find(f'{W}pPr/{W}pStyle')
            if style is not None and re.match(r'heading\d',style.get(W+'val',''),re.I):
                heading = text
            add(text, f'Paragraph {paragraph}' + (f' · {heading}' if heading else ''))
        elif block.tag == W+'tbl':
            table += 1
            for row_number, row in enumerate(block.findall(W+'tr'),1):
                for cell_number, cell in enumerate(row.findall(W+'tc'),1):
                    text = '\n'.join(paragraph_text(p).strip() for p in cell.findall(W+'p'))
                    add(text, f'Table {table}, row {row_number}, cell {cell_number}' + (f' · {heading}' if heading else ''))
    return {'pages':0,'chunks':chunks,'warning':None if chunks else 'No readable body paragraphs or tables in this DOCX.'}
