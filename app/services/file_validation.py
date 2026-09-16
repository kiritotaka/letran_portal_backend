import csv
from io import BytesIO, StringIO
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from zipfile import ZipFile
from app.core.errors import ApiError


def validate_file(filename, content, policy):
    name=(filename or '').replace('\\','/').split('/')[-1]
    if not name or len(name)>255 or any(ord(c)<32 for c in name):
        raise ApiError(422,'INVALID_FILENAME','Provide a valid filename.')
    if not content: raise ApiError(422,'EMPTY_FILE','File is empty.')
    if len(content)>policy.max_bytes: raise ApiError(413,'FILE_TOO_LARGE','Maximum file size is 10 MiB.')
    ext=PurePosixPath(name).suffix.lower()
    if ext not in policy.allowed_types:
        raise ApiError(415,'UNSUPPORTED_FILE_TYPE','This purpose accepts XLSX or UTF-8 CSV.')
    try:
        if ext=='.xlsx':
            validate_xlsx(content)
        elif ext=='.csv':
            text=content.decode('utf-8-sig')
            if not text.strip() or any(ord(c)<32 and c not in '\r\n\t' for c in text): raise ValueError()
            # No evaluation of Excel/CSV formulas. Business column validation belongs to import.
            rows=csv.reader(StringIO(text),strict=True)
            for index,row in enumerate(rows):
                if index>=200000 or len(row)>1000: raise ValueError()
    except Exception:
        raise ApiError(415,'INVALID_FILE_CONTENT','Invalid, encrypted or oversized workbook; CSV must be UTF-8.') from None
    return name,policy.allowed_types[ext]


def validate_xlsx(content):
    with ZipFile(BytesIO(content)) as z:
        entries=z.infolist(); names=z.namelist()
        if len(entries)>2000 or sum(e.file_size for e in entries)>50*1024*1024: raise ValueError()
        if len(names)!=len(set(names)): raise ValueError()
        if any(e.flag_bits & 1 for e in entries): raise ValueError()
        if any('vbaproject' in n.lower() or n.startswith('xl/embeddings/') for n in names): raise ValueError()
        roots={}
        for name in names:
            if name.endswith(('.xml','.rels')):
                data=z.read(name)
                if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper(): raise ValueError()
                if name in {'[Content_Types].xml','xl/workbook.xml'}:
                    roots[name]=ET.fromstring(data)
                else:
                    for event,node in ET.iterparse(BytesIO(data),events=('end',)): node.clear()
        root=roots['xl/workbook.xml']
        ns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
        if root.tag!='{'+ns+'}workbook' or root.find('{'+ns+'}sheets') is None: raise ValueError()
        expected='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml'
        if not any(n.get('PartName')=='/xl/workbook.xml' and n.get('ContentType')==expected for n in roots['[Content_Types].xml']): raise ValueError()
        if not any(n.startswith('xl/worksheets/') and n.endswith('.xml') for n in names): raise ValueError()
