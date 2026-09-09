import hashlib
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock
from zipfile import ZipFile
from threading import Event

import httpx
import pytest
from app.core.config import Settings
from app.dependencies.auth import Principal,current_user
from app.repositories.analysis import AnalysisRepository
from app.services.supabase import get_supabase_client
from app.services.document_analysis import AnalysisFailure,docx_text,source_parts,normalize,extract
from app.services.analysis_worker import process_job

UID='11111111-1111-4111-8111-111111111111'
RID='22222222-2222-4222-8222-222222222222'
FID='33333333-3333-4333-8333-333333333333'
JID='44444444-4444-4444-8444-444444444444'
SOURCE={'file_id':FID,'document_id':FID,'document_title':'Contract','document_type':'ECONOMIC_CONTRACT',
 'sort_order':1,'original_name':'contract.docx','bucket':'portal_documents','object_path':'private/path'}
JOB={'id':JID,'request_id':RID,'created_by':UID,'status':'queued','stage':'queued','model':'test-model',
 'schema_version':'acceptance-v1','source_snapshot':[SOURCE],'created_at':'2026-09-09T00:00:00Z','lease_token':FID}


@pytest.fixture
def sdk(app):
    c=MagicMock()
    app.app.dependency_overrides[get_supabase_client]=lambda:c
    app.app.dependency_overrides[current_user]=lambda:Principal(id=UID,is_super_admin=True,permissions=[])
    return c


def test_create_disabled(client,sdk):
    r=client.post(f'/api/v1/document-requests/{RID}/jobs',headers={'Idempotency-Key':JID})
    assert r.status_code==503
    assert r.json()['error']['code']=='AI_NOT_CONFIGURED'
    sdk.rpc.assert_not_called()


def test_enqueue_response_redacts_paths(app,client,sdk,monkeypatch):
    # Enable after TestClient started: do not launch a real worker from this test.
    app.app.state.settings.analysis_worker_enabled=True
    from pydantic import SecretStr
    app.app.state.settings.gemini_api_key=SecretStr('test-key')
    monkeypatch.setattr(AnalysisRepository,'enqueue',lambda *a:JOB)
    r=client.post(f'/api/v1/document-requests/{RID}/jobs',headers={'Idempotency-Key':JID})
    assert r.status_code==202
    assert r.json()['data']['id']==JID
    assert 'private/path' not in r.text and 'lease_token' not in r.text
    assert r.headers['cache-control']=='no-store'


@pytest.mark.parametrize('method,path,permission',[
 ('post',f'/document-requests/{RID}/jobs','DOC_VIEW'),
 ('get',f'/document-jobs/{JID}','DOC_UPDATE')])
def test_job_permissions(app,client,sdk,method,path,permission):
    app.app.dependency_overrides[current_user]=lambda:Principal(id=UID,is_super_admin=False,permissions=[permission])
    assert getattr(client,method)('/api/v1'+path,headers={'Idempotency-Key':JID}).status_code==403
    sdk.rpc.assert_not_called()


def test_get_job_after_reload(client,sdk,monkeypatch):
    monkeypatch.setattr(AnalysisRepository,'get',lambda *a:JOB)
    r=client.get('/api/v1/document-jobs/'+JID)
    assert r.status_code==200 and r.json()['data']['status']=='queued'


def docx(image=False):
    b=BytesIO()
    with ZipFile(b,'w') as z:
        z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Contract ETEC 123</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Amount 100</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
        if image:z.writestr('word/media/image.png',b'fake')
    return b.getvalue()


def test_docx_and_hash():
    data=docx();assert 'Amount 100' in docx_text(data)
    source={**SOURCE,'content_type':'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            'size_bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    parts,text=source_parts([source],[data])
    assert 'ETEC' in text[FID]
    assert all('inlineData' not in p for p in parts)
    with pytest.raises(AnalysisFailure) as exc:source_parts([{**source,'sha256':'bad'}],[data])
    assert exc.value.code=='SOURCE_CHANGED'
    with pytest.raises(AnalysisFailure) as exc:docx_text(docx(True))
    assert exc.value.code=='DOCX_IMAGES_REQUIRE_PDF'


def field(name='contract_number',value='123',quote='ETEC 123',file_id=FID,conflict=False):
    return {'name':name,'value':value,'sources':[{'file_id':file_id,'location':'paragraph 1','quote':quote}],'conflict':conflict}


def test_normalize_manual_missing_conflicts_and_payment():
    raw={'fields':[field(),field('acceptance_date'),field('paid_amount'),field('party_a_name',conflict=True)]}
    result=normalize(raw,[SOURCE],{FID:'ETEC 123'})
    values={f['name']:f for f in result['fields']}
    assert len(values)==24
    assert values['contract_number']['value']=='123'
    assert values['acceptance_date']['value'] is None
    assert values['paid_amount']['value'] is None
    assert values['party_a_name']['status']=='conflict'
    assert result['requires_review'] is True
    assert 'contract_total' in result['missing_fields']


def test_unverified_quote_is_not_used():
    result=normalize({'fields':[field(quote='made up')]},[SOURCE],{FID:'ETEC 123'})
    assert next(f for f in result['fields'] if f['name']=='contract_number')['value'] is None


def test_unknown_source_rejected():
    with pytest.raises(AnalysisFailure) as exc:normalize({'fields':[field(file_id=UID)]},[SOURCE],{})
    assert exc.value.code=='AI_INVALID_SOURCE'


@pytest.mark.parametrize('fields',[[field(),field()],[{**field(),'name':'report_number'}]])
def test_invalid_fields_rejected(fields):
    with pytest.raises(ValueError):normalize({'fields':fields},[SOURCE],{})


def test_gemini_http_contract():
    def handle(req):
        assert req.url.host=='generativelanguage.googleapis.com'
        assert 'test-secret' not in str(req.url)
        assert req.headers['x-goog-api-key']=='test-secret'
        body=json.loads(req.content)
        assert 'tools' not in body
        assert body['generationConfig']['responseMimeType']=='application/json'
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps({'fields':[field()]})}]}}]})
    result=extract(Settings(_env_file=None,gemini_api_key='test-secret'),'gemini-2.5-flash',[],[SOURCE],{FID:'ETEC 123'},httpx.MockTransport(handle))
    assert result['requires_review']


@pytest.mark.parametrize('status,code',[(429,'AI_RATE_LIMITED'),(403,'AI_CREDENTIALS_REJECTED'),(404,'AI_MODEL_UNAVAILABLE'),(500,'AI_PROVIDER_ERROR')])
def test_provider_errors_redacted(status,code):
    with pytest.raises(AnalysisFailure) as exc:
        extract(Settings(_env_file=None),'test-model',[],[],{},httpx.MockTransport(lambda r:httpx.Response(status,text='private-secret')))
    assert exc.value.code==code


def test_worker_failure_persisted(monkeypatch):
    import app.services.analysis_worker as worker
    monkeypatch.setattr(worker,'verify_access',lambda *a:None)
    c=MagicMock(); c.storage.from_.return_value.download.side_effect=RuntimeError('private-secret')
    finished=[]
    monkeypatch.setattr(AnalysisRepository,'finish',lambda self,job,**kwargs:finished.append(kwargs))
    process_job(c,Settings(_env_file=None),JOB,Event())
    assert finished==[{'error':'ANALYSIS_FAILED'}]


def test_worker_persists_success(monkeypatch):
    import app.services.analysis_worker as worker
    monkeypatch.setattr(worker,'verify_access',lambda *a:None)
    monkeypatch.setattr(worker,'source_parts',lambda *a:([],{}))
    result=normalize({'fields':[]},[],{})
    monkeypatch.setattr(worker,'extract',lambda *a:result)
    finished=[]
    monkeypatch.setattr(AnalysisRepository,'finish',lambda self,job,**kwargs:finished.append(kwargs))
    process_job(MagicMock(),Settings(_env_file=None),JOB,Event())
    assert finished==[{'result':result}]


@pytest.mark.parametrize('basis,expected', [('actual_confirmed','extracted'), ('planned','needs_input'), ('unknown','needs_input')])
def test_actual_evidence_not_blanket_discarded(basis, expected):
    item={**field('acceptance_date', '09/09/2026', 'Accepted on 09/09/2026'), 'basis':basis}
    result=normalize({'fields':[item]},[SOURCE],{FID:'Accepted on 09/09/2026'})
    assert result['fields'][0]['status']==expected


def test_copy_counts_must_describe_target_report():
    for basis,expected in [('explicit','needs_input'),('target_report','extracted')]:
        item={**field('copy_count','2','Report has 2 copies'),'basis':basis}
        result=normalize({'fields':[item]},[SOURCE],{FID:'Report has 2 copies'})
        assert next(f for f in result['fields'] if f['name']=='copy_count')['status']==expected


def test_whitespace_evidence_and_exact_subject():
    item=field('service_description','(V/v: Robot training)','V/v: Robot training')
    result=normalize({'fields':[item]},[SOURCE],{FID:'V/v:\nRobot\ttraining'})
    assert next(f for f in result['fields'] if f['name']=='service_description')['value']=='Robot training'


def test_payment_proof_requires_actual_basis():
    source={**SOURCE,'document_type':'PAYMENT_PROOF'}
    for basis,expected in [('planned','missing'),('actual_confirmed','extracted')]:
        item={**field('paid_amount','123'),'basis':basis}
        result=normalize({'fields':[item]},[source],{FID:'ETEC 123'})
        assert next(f for f in result['fields'] if f['name']=='paid_amount')['status']==expected
