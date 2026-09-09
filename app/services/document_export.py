import hashlib
import re
from io import BytesIO
from zipfile import ZipFile, ZIP_DEFLATED, ZipInfo
from xml.dom import minidom
from app.core.errors import ApiError
from app.repositories.document_review import ReviewRepository
from app.repositories.documents import DocumentRepository
from app.schemas.document_review import SaveReview, MONEY

W = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
MARKER = re.compile(r'{{\s*([a-z_]+)\s*}}')
MAX_TEMPLATE = 10 * 1024 * 1024


def fill_docx(template, values):
    """Replace plain placeholders across Word runs; never execute template code."""
    if len(template)>MAX_TEMPLATE:
        raise ApiError(422,'TEMPLATE_INVALID','Template exceeds size limit.')
    out=BytesIO(); replaced=set()
    try:
        with ZipFile(BytesIO(template)) as src, ZipFile(out,'w',ZIP_DEFLATED) as dst:
            if len(src.infolist())>2000 or sum(i.file_size for i in src.infolist())>50*1024*1024:
                raise ValueError()
            if len(set(src.namelist()))!=len(src.namelist()) or 'word/document.xml' not in src.namelist():
                raise ValueError()
            for item in src.infolist():
                if 'vbaproject' in item.filename.lower(): raise ValueError()
                data=src.read(item.filename)
                if item.filename=='word/document.xml' or (item.filename.startswith(('word/header','word/footer')) and item.filename.endswith('.xml')):
                    if b'<!DOCTYPE' in data.upper() or b'<!ENTITY' in data.upper(): raise ValueError()
                    dom=minidom.parseString(data)
                    for para in dom.getElementsByTagNameNS(W,'p'):
                        nodes=[]
                        for node in para.getElementsByTagNameNS(W,'t'):
                            parent=node.parentNode
                            while parent is not None and not (parent.namespaceURI==W and parent.localName=='p'):
                                parent=parent.parentNode
                            if parent is para: nodes.append(node)
                        texts=[''.join(c.data for c in n.childNodes if c.nodeType==c.TEXT_NODE) for n in nodes]
                        joined=''.join(texts)
                        matches=list(MARKER.finditer(joined))
                        if '{{' in MARKER.sub('',joined) or '}}' in MARKER.sub('',joined): raise ValueError()
                        offsets=[]; pos=0
                        for text in texts: offsets.append((pos,pos+len(text))); pos+=len(text)
                        for match in reversed(matches):
                            name=match.group(1)
                            if name not in values: raise ValueError()
                            replacement=values[name] or ''
                            if name in MONEY and replacement: replacement=format(int(replacement),',')
                            for index,(start,end) in enumerate(offsets):
                                if end<=match.start() or start>=match.end(): continue
                                left=max(0,match.start()-start); right=min(end-start,match.end()-start)
                                insert=replacement if start<=match.start()<end else ''
                                texts[index]=texts[index][:left]+insert+texts[index][right:]
                            replaced.add(name)
                        for node,text in zip(nodes,texts):
                            for child in list(node.childNodes): node.removeChild(child)
                            node.appendChild(dom.createTextNode(text))
                            node.setAttribute('xml:space','preserve')
                    data=dom.toxml(encoding='utf-8')
                # Stable ZIP timestamps make repeated exports deterministic.
                info=ZipInfo(item.filename,(1980,1,1,0,0,0)); info.compress_type=ZIP_DEFLATED
                dst.writestr(info,data)
        if not replaced: raise ValueError()
    except Exception:
        raise ApiError(422,'TEMPLATE_INVALID','Template contains invalid or unsupported placeholders/content.') from None
    if len(out.getvalue())>MAX_TEMPLATE:
        raise ApiError(422,'EXPORT_TOO_LARGE','Generated document exceeds storage limit.')
    return out.getvalue()


def export_url(client, review, exported):
    filename=f'acceptance-report-v{review["revision"]}.docx'
    try:
        signed=client.storage.from_('portal_documents').create_signed_url(exported['object_path'],300,{'download':filename})
        url=signed['signedURL']
        if not isinstance(url,str) or not url.startswith('https://'): raise ValueError()
    except Exception:
        raise ApiError(503,'STORAGE_UNAVAILABLE','Export URL unavailable; request it again.') from None
    return {'review_id':review['id'],'revision':review['revision'],'filename':filename,'download_url':url,'expires_in':300}


def create_export(client,actor,request_id,revision):
    repo=ReviewRepository(client)
    request=DocumentRepository(client).one('portal_document_requests',request_id)
    if request['status']!='draft': raise ApiError(409,'REQUEST_ARCHIVED','Request is archived.')
    review=repo.get(request_id,revision)
    if not review['confirmed']: raise ApiError(409,'REVIEW_NOT_CONFIRMED','Confirm reviewed data before exporting.')
    # Revalidate stored data too, before generating any file.
    try:
        validated=SaveReview(analysis_job_id=review['analysis_job_id'],expected_revision=revision-1,
                             confirmed=True,fields=review['fields'])
    except Exception:
        raise ApiError(422,'REVIEW_INVALID','Saved data is incomplete or invalid.') from None
    existing=repo.exported(review['id'])
    if existing: return export_url(client,review,existing)
    path=review['template_path']
    if not path.startswith('templates/'):
        raise ApiError(422,'TEMPLATE_INVALID','Invalid template location.')
    try:
        template=client.storage.from_('portal_documents').download(path)
    except Exception:
        raise ApiError(503,'TEMPLATE_UNAVAILABLE','Cannot download the assigned template.') from None
    content=fill_docx(template,{f.name:f.value for f in validated.fields})
    digest=hashlib.sha256(content).hexdigest()
    path=f'exports/{request_id}/{review["id"]}/{digest}.docx'
    try:
        client.storage.from_('portal_documents').upload(path,content,file_options={
            'content-type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'upsert':'true','cache-control':'0'})
    except Exception:
        raise ApiError(503,'EXPORT_UNCONFIRMED','Export upload unconfirmed; retry the same revision.') from None
    exported=repo.finish_export(actor,review['id'],path,digest)
    return export_url(client,review,exported)
