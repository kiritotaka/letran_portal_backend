from io import BytesIO
from zipfile import ZipFile
from types import SimpleNamespace
from unittest.mock import MagicMock
import pytest
from app.core.errors import ApiError
from app.dependencies.auth import Principal,current_user
from app.services.supabase import get_supabase_client
from app.services.file_policies import POLICIES
from app.services.file_validation import validate_file
from app.repositories.files import FileRepository
from app.services.files import upload_file

UID='11111111-1111-4111-8111-111111111111'
FID='22222222-2222-4222-8222-222222222222'
ROW={'id':FID,'purpose':'product_import','original_name':'products.csv','content_type':'text/csv',
 'size_bytes':10,'status':'ready','created_by':UID,'created_at':'2026-09-16T00:00:00Z',
 'updated_at':'2026-09-16T00:00:00Z','bucket':'portal_uploads','object_path':'private/path','sha256':'a'*64}


@pytest.fixture
def sdk(app):
    c=MagicMock()
    app.app.dependency_overrides[get_supabase_client]=lambda:c
    app.app.dependency_overrides[current_user]=lambda:Principal(id=UID,is_super_admin=False,permissions=['PRODUCT_IMPORT'])
    return c


def test_upload_and_metadata_redacted(client,sdk,monkeypatch):
    monkeypatch.setattr(FileRepository,'action',lambda *a,**kw:ROW)
    r=client.post('/api/v1/files',data={'purpose':'product_import'},files={'file':('products.csv',b'code,name\nA,B')},headers={'Idempotency-Key':FID})
    assert r.status_code==200
    assert r.json()['data']['id']==FID
    assert all(x not in r.json()['data'] for x in ('bucket','object_path','sha256'))
    assert r.headers['cache-control']=='no-store'
    sdk.storage.from_.assert_not_called() # completed retry
    assert client.get('/api/v1/files/'+FID).status_code==200


def test_upload_reserve_storage_complete(sdk,monkeypatch):
    calls=[]
    def action(self,actor,op,*args):
        calls.append(op)
        return {**ROW,'status':'uploading' if op=='reserve' else 'ready'}
    monkeypatch.setattr(FileRepository,'action',action)
    result=upload_file(sdk,Principal(id=UID,is_super_admin=True,permissions=[]),FID,'product_import',
         SimpleNamespace(filename='products.csv',file=BytesIO(b'code,name\nA,B')))
    assert result['status']=='ready' and calls==['reserve','complete']
    sdk.storage.from_.assert_called_once_with('portal_uploads')


def test_no_permission_upload(app,client,sdk):
    app.app.dependency_overrides[current_user]=lambda:Principal(id=UID,is_super_admin=False,permissions=['DOC_CREATE'])
    r=client.post('/api/v1/files',data={'purpose':'product_import'},files={'file':('p.csv',b'a,b')},headers={'Idempotency-Key':FID})
    assert r.status_code==403
    sdk.rpc.assert_not_called()


@pytest.mark.parametrize('name,data,status', [('a.xls',b'x',415),('a.xlsx',b'not zip',415),('a.csv',b'',422),('a.csv',b'\x00binary',415),('a.csv',b'x'*(10*1024*1024+1),413)],ids=['extension','not_zip','empty','binary','size'])
def test_validation(name,data,status):
    with pytest.raises(ApiError) as exc:validate_file(name,data,POLICIES['product_import'])
    assert exc.value.status==status


def test_xlsx_xml_entities_rejected():
    b=BytesIO()
    with ZipFile(b,'w') as z:z.writestr('xl/workbook.xml','<!DOCTYPE x [<!ENTITY x "x">]><x/>')
    with pytest.raises(ApiError): validate_file('x.xlsx',b.getvalue(),POLICIES['product_import'])


def test_download_blocked_before_ready(client,sdk,monkeypatch):
    monkeypatch.setattr(FileRepository,'action',lambda *a,**kw:{**ROW,'status':'deleted'})
    assert client.get('/api/v1/files/'+FID+'/download-url').status_code==409
    sdk.storage.from_.assert_not_called()


def test_signed_url_and_delete(client,sdk,monkeypatch):
    monkeypatch.setattr(FileRepository,'action',lambda *a,**kw:ROW)
    sdk.storage.from_.return_value.create_signed_url.return_value={'signedURL':'https://example.com/signed'}
    r=client.get('/api/v1/files/'+FID+'/download-url')
    assert r.status_code==200 and r.json()['data']['expires_in']==300
    assert client.delete('/api/v1/files/'+FID).status_code==200
    r=client.options('/api/v1/files/'+FID,headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'DELETE','Access-Control-Request-Headers':'authorization'})
    assert r.status_code==200


def test_unknown_purpose_and_body_limit(client,sdk):
    r=client.post('/api/v1/files',data={'purpose':'unknown'},files={'file':('p.csv',b'a,b')},headers={'Idempotency-Key':FID})
    assert r.status_code==422
    r=client.post('/api/v1/files',content=b'x'*(11*1024*1024+1))
    assert r.status_code==413
    sdk.rpc.assert_not_called()
