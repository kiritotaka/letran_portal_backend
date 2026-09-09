from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from uuid import uuid4
from zipfile import ZipFile

import httpx
import pytest
from PIL import Image
from pypdf import PdfWriter
from postgrest.exceptions import APIError

from app.core.errors import ApiError
from app.dependencies.auth import Principal, current_user
from app.repositories.documents import DocumentRepository
from app.services.document_uploads import inspect_file, MAX_FILE_BYTES
from app.services.supabase import get_supabase_client

UID = '11111111-1111-4111-8111-111111111111'
RID = '22222222-2222-4222-8222-222222222222'
DID = '33333333-3333-4333-8333-333333333333'
FID = '44444444-4444-4444-8444-444444444444'
DATE = '2026-09-09T00:00:00Z'
PATH = f'/api/v1/document-requests/{RID}/documents/{DID}/files'
ROW = dict(id=FID, bucket='portal_documents', object_path=f'{RID}/{DID}/{FID}',
           original_name='test.png', content_type='image/png', size_bytes=70,
           status='uploading', created_by=UID, created_at=DATE, updated_at=DATE)


def picture(fmt='PNG'):
    b = BytesIO()
    Image.new('RGB', (2, 2)).save(b, format=fmt)
    return b.getvalue()


@pytest.fixture
def sdk(app):
    sdk = MagicMock()
    app.app.dependency_overrides[get_supabase_client] = lambda: sdk
    app.app.dependency_overrides[current_user] = lambda: Principal(id=UID, is_super_admin=True, permissions=[])
    sdk.rpc.return_value.execute.side_effect = [SimpleNamespace(data=ROW), SimpleNamespace(data={**ROW, 'status':'ready'})]
    return sdk


def test_upload_validates_and_completes(client, sdk):
    response = client.post(PATH, headers={'Idempotency-Key':FID}, data={'sort_order':2},
                           files={'file':('test.png',picture(),'application/incorrect')})
    assert response.status_code == 200
    assert response.json()['data']['status'] == 'ready'
    assert 'object_path' not in response.text and 'bucket' not in response.text
    assert response.headers['cache-control'] == 'no-store'
    first = sdk.rpc.call_args_list[0].args[1]
    assert first['p_data']['content_type'] == 'image/png'
    assert first['p_data']['sort_order'] == 2
    assert first['p_actor_id'] == UID
    sdk.storage.from_.return_value.upload.assert_called_once()


def test_retry_completed_file_does_not_upload(client, sdk):
    sdk.rpc.return_value.execute.side_effect = [SimpleNamespace(data={**ROW,'status':'ready'})]
    assert client.post(PATH,headers={'Idempotency-Key':FID},files={'file':('test.png',picture())}).status_code == 200
    sdk.storage.from_.return_value.upload.assert_not_called()


@pytest.mark.parametrize('key', [None,'not-a-uuid'])
def test_requires_retry_key(client,sdk,key):
    response=client.post(PATH,headers={} if key is None else {'Idempotency-Key':key},files={'file':('test.png',picture())})
    assert response.status_code==422
    sdk.rpc.assert_not_called()


def test_missing_sql_never_writes_storage(client,sdk):
    sdk.rpc.return_value.execute.side_effect=APIError({'message':'missing','code':'PGRST202','hint':None,'details':None})
    response=client.post(PATH,headers={'Idempotency-Key':FID},files={'file':('test.png',picture())})
    assert response.json()['error']['code']=='DOCUMENTS_NOT_INSTALLED'
    sdk.storage.from_.assert_not_called()


def test_storage_failure_retains_retry_reservation(client,sdk):
    sdk.storage.from_.return_value.upload.side_effect=RuntimeError('private key')
    response=client.post(PATH,headers={'Idempotency-Key':FID},files={'file':('test.png',picture())})
    assert response.status_code==503
    assert response.json()['error']['code']=='UPLOAD_UNCONFIRMED'
    assert sdk.rpc.call_count==1
    assert 'private key' not in response.text


def test_finalize_failure_explicit(client,sdk):
    sdk.rpc.return_value.execute.side_effect=[SimpleNamespace(data=ROW),RuntimeError()]
    response=client.post(PATH,headers={'Idempotency-Key':FID},files={'file':('test.png',picture())})
    assert response.json()['error']['code']=='UPLOAD_FINALIZATION_UNCONFIRMED'


@pytest.mark.parametrize('name,data,status',[
    ('test.png',b'',422),('test.png',b'not an image',415),('test.jpg',picture(),415),
    ('test.exe',b'file',415),('test.pdf',b'%PDF-1.7 fake',415),('test.docx',b'PK fake',415),
    ('big.png',b'x'*(MAX_FILE_BYTES+1),413)], ids=['empty','fake-image','wrong-extension','exe','fake-pdf','fake-docx','oversize'])
def test_invalid_file(name,data,status):
    with pytest.raises(ApiError) as error:
        inspect_file(name,data)
    assert error.value.status==status


def test_supported_structures_and_filename():
    assert inspect_file('../nested/test.png',picture())[0]=='test.png'
    assert inspect_file('test.jpg',picture('JPEG'))[1]=='image/jpeg'
    writer=PdfWriter(); writer.add_blank_page(width=100,height=100)
    pdf=BytesIO(); writer.write(pdf)
    assert inspect_file('test.pdf',pdf.getvalue())[1]=='application/pdf'
    writer.encrypt('password'); encrypted=BytesIO(); writer.write(encrypted)
    with pytest.raises(ApiError): inspect_file('test.pdf',encrypted.getvalue())
    doc=BytesIO()
    with ZipFile(doc,'w') as z:
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body/></w:document>')
        z.writestr('[Content_Types].xml','<Types><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
    assert inspect_file('test.docx',doc.getvalue())[1].endswith('document')


@pytest.mark.parametrize('method,path,body,permission',[
 ('get','/document-requests',None,'DOC_VIEW'),
 ('get',f'/document-requests/{RID}/files/{FID}/download-url',None,'DOC_VIEW'),
 ('post','/document-requests',{'task_id':DID,'title':'Test'},'DOC_CREATE'),
 ('patch',f'/document-requests/{RID}',{'title':'Test'},'DOC_UPDATE'),
 ('post',f'/document-requests/{RID}/files/{FID}/delete',None,'DOC_REMOVE'),
])
def test_permission_denial(app,client,sdk,method,path,body,permission):
    app.app.dependency_overrides[current_user]=lambda:Principal(id=UID,is_super_admin=False,permissions=['USER_VIEW'])
    kwargs={} if body is None else {'json':body}
    assert getattr(client,method)('/api/v1'+path,**kwargs).status_code==403
    sdk.rpc.assert_not_called()
    sdk.table.assert_not_called()


@pytest.mark.parametrize('status',['uploading','deleted'])
def test_unready_file_cannot_get_url(client,sdk,monkeypatch,status):
    monkeypatch.setattr(DocumentRepository,'file_for_request',lambda *a:{**ROW,'status':status})
    response=client.get(f'/api/v1/document-requests/{RID}/files/{FID}/download-url')
    assert response.status_code==409
    sdk.storage.from_.assert_not_called()


def test_private_download(client,sdk,monkeypatch):
    monkeypatch.setattr(DocumentRepository,'file_for_request',lambda *a:{**ROW,'status':'ready'})
    sdk.storage.from_.return_value.create_signed_url.return_value={'signedURL':'https://example.supabase.co/private?token=temporary'}
    response=client.get(f'/api/v1/document-requests/{RID}/files/{FID}/download-url')
    assert response.status_code==200
    assert response.json()['data']['expires_in']==300
    assert response.headers['cache-control']=='no-store'
    sdk.storage.from_.return_value.create_signed_url.assert_called_once_with(ROW['object_path'],300,{'download':'test.png'})


def test_paginated_requests(client,sdk,monkeypatch):
    monkeypatch.setattr(DocumentRepository,'page',lambda *a,**kw:SimpleNamespace(data=[],count=41))
    response=client.get('/api/v1/document-requests?page=2&page_size=20')
    assert response.status_code==200
    assert response.json()['data']['pagination']['total_pages']==3
    assert response.json()['data']['pagination']['has_next'] is True


@pytest.mark.parametrize('document_id',[None,DID])
def test_files_flat_query_parameters(client,sdk,monkeypatch,document_id):
    monkeypatch.setattr(DocumentRepository,'one',lambda *a:{'request_id':RID})
    seen=[]
    def page(self,table,params,filters,**kwargs):
        seen.append((params.page,params.page_size,filters))
        return SimpleNamespace(data=[],count=0)
    monkeypatch.setattr(DocumentRepository,'page',page)
    query={'page':1,'page_size':100}
    if document_id: query['document_id']=document_id
    response=client.get(f'/api/v1/document-requests/{RID}/files',params=query)
    assert response.status_code==200
    assert seen[0][:2]==(1,100)
    assert str(seen[0][2].get('document_id'))==str(document_id)


def test_files_openapi_parameters(client):
    parameters=client.get('/openapi.json').json()['paths']['/api/v1/document-requests/{request_id}/files']['get']['parameters']
    assert {p['name'] for p in parameters}=={'request_id','page','page_size','document_id'}


@pytest.mark.parametrize('query',[{'page_size':101},{'page':0},{'document_id':'invalid'}])
def test_files_invalid_query(client,sdk,query):
    assert client.get(f'/api/v1/document-requests/{RID}/files',params=query).status_code==422
    sdk.table.assert_not_called()


def test_bad_pagination_and_body(client,sdk):
    assert client.get('/api/v1/document-types?page_size=101').status_code==422
    assert client.patch(f'/api/v1/document-requests/{RID}',json={}).status_code==422
    assert client.post('/api/v1/document-requests',json={'task_id':DID,'title':'   '}).status_code==422


@pytest.mark.parametrize('query',['document_type_id=bad','search='+('x'*201),'page=0'])
def test_search_validation(client,sdk,query):
    assert client.get('/api/v1/document-requests?'+query).status_code==422
    sdk.rpc.assert_not_called()


def test_search_parameters_and_pagination(client,sdk):
    sdk.rpc.return_value.order.return_value.order.return_value.range.return_value.execute.return_value=SimpleNamespace(data=[],count=31)
    response=client.get('/api/v1/document-requests',params={'document_type_id':DID,'search':'  ETEC  ','page':2,'page_size':5})
    assert response.status_code==200
    sdk.rpc.assert_called_once_with('portal_search_document_requests',{'p_document_type_id':DID,'p_search':'ETEC'},count='exact')
    sdk.rpc.return_value.order.return_value.order.return_value.range.assert_called_once_with(5,9)
    assert response.json()['data']['pagination']['total']==31


def test_missing_search_migration(client,sdk):
    sdk.rpc.return_value.order.return_value.order.return_value.range.return_value.execute.side_effect=APIError({'message':'missing','code':'PGRST202','hint':None,'details':None})
    response=client.get('/api/v1/document-requests?search=test')
    assert response.status_code==503
    assert response.json()['error']['code']=='DOCUMENT_SEARCH_NOT_INSTALLED'


def test_cors_upload_key(client):
    response=client.options(PATH,headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'POST',
        'Access-Control-Request-Headers':'authorization,idempotency-key,content-type'})
    assert response.status_code==200


def test_transport_body_limit(client,sdk):
    response=client.post(PATH,content=b'x'*(11*1024*1024+1),headers={'Origin':'http://localhost:5173'})
    assert response.status_code==413
    assert response.headers['access-control-allow-origin']=='http://localhost:5173'
    sdk.rpc.assert_not_called()


def test_real_sdk_upload_transport(monkeypatch):
    import json
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.main import create_app
    import app.services.supabase as service
    original=httpx.Client
    seen=[]
    def handle(request):
        seen.append(request)
        assert request.headers['authorization']=='Bearer test-service-key'
        if request.url.path=='/rest/v1/rpc/portal_documents_write':
            body=json.loads(request.content)
            row={**ROW,'status':'ready' if body['p_action']=='complete_file' else 'uploading'}
            return httpx.Response(200,json=row)
        assert request.url.path=='/storage/v1/object/portal_documents/'+ROW['object_path']
        assert request.headers['x-upsert']=='true'
        assert request.headers['content-type'].startswith('multipart/form-data')
        assert b'Content-Type: image/png' in request.content
        return httpx.Response(200,json={'Key':'portal_documents/'+ROW['object_path'],'Id':FID})
    monkeypatch.setattr(service.httpx,'Client',lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    app=create_app(Settings(_env_file=None,supabase_url='https://example.supabase.co',supabase_service_role_key='test-service-key'))
    app.app.dependency_overrides[current_user]=lambda:Principal(id=UID,is_super_admin=True,permissions=[])
    with TestClient(app) as c:
        response=c.post(PATH,headers={'Idempotency-Key':FID},files={'file':('test.png',picture())})
    assert response.status_code==200
    assert len(seen)==3
