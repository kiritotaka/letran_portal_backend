from io import BytesIO
from zipfile import ZipFile
from typing import get_args
from unittest.mock import MagicMock
import pytest
from pydantic import ValidationError
from app.schemas.analysis import FieldName
from app.schemas.document_review import SaveReview, MONEY, DATES
from app.services.document_export import fill_docx, create_export
from app.core.errors import ApiError
from app.dependencies.auth import Principal, current_user
from app.services.supabase import get_supabase_client
from app.repositories.document_review import ReviewRepository
from app.repositories.documents import DocumentRepository

UID='11111111-1111-4111-8111-111111111111'
RID='22222222-2222-4222-8222-222222222222'
JID='33333333-3333-4333-8333-333333333333'


def payload(confirmed=True):
    fields=[]
    for name in get_args(FieldName):
        value='Sample & text'
        if name in MONEY: value='1101600000'
        if name in DATES: value='09/09/2026'
        if name in {'copy_count','copies_per_party'}: value='2'
        fields.append({'name':name,'value':value})
    return {'analysis_job_id':JID,'expected_revision':0,'confirmed':confirmed,'fields':fields}


@pytest.mark.parametrize('field,value',[('contract_total','1,000'),('paid_amount','2.5'),('acceptance_date','31/02/2026'),('copy_count','0'),('party_a_name','{{ injected }}')])
def test_review_rejects_invalid_values(field,value):
    p=payload()
    next(f for f in p['fields'] if f['name']==field)['value']=value
    with pytest.raises(ValidationError): SaveReview(**p)


def test_draft_allows_missing_but_confirmed_requires_values():
    p=payload(False); p['fields'][0]['value']=None
    SaveReview(**p)
    p['confirmed']=True
    with pytest.raises(ValidationError): SaveReview(**p)


def test_duplicate_and_date_order():
    p=payload();p['fields'][0]=p['fields'][1]
    with pytest.raises(ValidationError): SaveReview(**p)
    p=payload()
    next(f for f in p['fields'] if f['name']=='actual_start_date')['value']='10/09/2026'
    with pytest.raises(ValidationError): SaveReview(**p)


def template(text):
    stream=BytesIO()
    with ZipFile(stream,'w') as z:
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'+text+'</w:body></w:document>')
        z.writestr('word/styles.xml','unchanged')
    return stream.getvalue()


def test_docx_split_runs_escaping_money_and_determinism():
    src=template('<w:p><w:r><w:rPr><w:b/></w:rPr><w:t>{{party_a_</w:t></w:r><w:r><w:t>name}} / {{contract_total}}</w:t></w:r></w:p>')
    values={'party_a_name':'A & B <test>','contract_total':'1101600000'}
    result=fill_docx(src,values)
    assert result==fill_docx(src,values)
    with ZipFile(BytesIO(result)) as z:
        xml=z.read('word/document.xml').decode()
        assert 'A &amp; B &lt;test&gt;' in xml and '1,101,600,000' in xml
        assert '{{' not in xml and '<w:b/>' in xml
        assert z.read('word/styles.xml')==b'unchanged'


def test_unknown_template_marker_rejected():
    with pytest.raises(ApiError): fill_docx(template('<w:p><w:r><w:t>{{unknown}}</w:t></w:r></w:p>'),{})


@pytest.fixture
def sdk(app):
    c=MagicMock()
    app.app.dependency_overrides[get_supabase_client]=lambda:c
    app.app.dependency_overrides[current_user]=lambda:Principal(id=UID,is_super_admin=True,permissions=[])
    return c


def test_route_saves_and_redacts_internal_columns(client,sdk,monkeypatch):
    p=payload()
    row={**p,'id':JID,'request_id':RID,'revision':1,'template_id':JID,'created_by':UID,
         'created_at':'2026-09-09T00:00:00Z','template_path':'private/path','original_payload':p}
    monkeypatch.setattr(ReviewRepository,'save',lambda *args:row)
    r=client.put(f'/api/v1/document-requests/{RID}/review',json=p,headers={'Idempotency-Key':JID})
    assert r.status_code==200
    assert 'private/path' not in r.text and 'original_payload' not in r.text
    assert r.headers['cache-control']=='no-store'


@pytest.mark.parametrize('method,path,body',[
 ('put','review',payload()),('post','exports',{'revision':1})])
def test_viewer_cannot_write(app,client,sdk,method,path,body):
    app.app.dependency_overrides[current_user]=lambda:Principal(id=UID,is_super_admin=False,permissions=['DOC_VIEW'])
    r=getattr(client,method)(f'/api/v1/document-requests/{RID}/{path}',json=body,headers={'Idempotency-Key':JID})
    assert r.status_code==403
    sdk.rpc.assert_not_called()


def test_unconfirmed_export_does_not_upload(monkeypatch):
    c=MagicMock()
    monkeypatch.setattr(DocumentRepository,'one',lambda *args:{'status':'draft'})
    monkeypatch.setattr(ReviewRepository,'get',lambda *args:{'confirmed':False})
    with pytest.raises(ApiError) as exc: create_export(c,object(),RID,1)
    assert exc.value.code=='REVIEW_NOT_CONFIRMED'
    c.storage.from_.assert_not_called()



def test_export_success_retry_and_signing_failure(monkeypatch):
    c=MagicMock(); p=payload()
    review={**p,'id':JID,'request_id':RID,'revision':1,'template_path':'templates/v1.docx'}
    monkeypatch.setattr(DocumentRepository,'one',lambda *args:{'status':'draft'})
    monkeypatch.setattr(ReviewRepository,'get',lambda *args:review)
    stored=[]
    monkeypatch.setattr(ReviewRepository,'exported',lambda *args:stored[0] if stored else None)
    def finish(self,actor,id,path,digest):
        stored.append({'object_path':path,'sha256':digest})
        return stored[0]
    monkeypatch.setattr(ReviewRepository,'finish_export',finish)
    c.storage.from_.return_value.download.return_value=template('<w:p><w:r><w:t>{{contract_total}}</w:t></w:r></w:p>')
    c.storage.from_.return_value.create_signed_url.return_value={'signedURL':'https://example.com/result'}
    first=create_export(c,object(),RID,1)
    second=create_export(c,object(),RID,1)
    assert first==second
    c.storage.from_.return_value.upload.assert_called_once()
    c.storage.from_.return_value.download.assert_called_once_with('templates/v1.docx')
    c.storage.from_.return_value.create_signed_url.side_effect=RuntimeError('private-secret')
    with pytest.raises(ApiError) as exc:create_export(c,object(),RID,1)
    assert exc.value.code=='STORAGE_UNAVAILABLE'
    assert 'private-secret' not in exc.value.message


def test_reload_review(client,sdk,monkeypatch):
    monkeypatch.setattr(DocumentRepository,'one',lambda *args:{'id':RID})
    row={**payload(),'id':JID,'request_id':RID,'revision':1,'template_id':JID,'created_by':UID,
         'created_at':'2026-09-09T00:00:00Z'}
    monkeypatch.setattr(ReviewRepository,'get',lambda *args:row)
    r=client.get(f'/api/v1/document-requests/{RID}/review')
    assert r.status_code==200
    assert r.json()['data']['revision']==1
