from io import BytesIO
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from PIL import Image
from postgrest.exceptions import APIError

from app.dependencies.auth import Principal, current_user
from app.repositories.service_files import ServiceFileRepository
from app.services.supabase import get_supabase_client

UID = '11111111-1111-4111-8111-111111111111'
RID = '22222222-2222-4222-8222-222222222222'
FID = '44444444-4444-4444-8444-444444444444'
DATE = '2026-09-16T00:00:00Z'
PATH = f'/api/v1/service-requests/{RID}/files'
ROW = dict(id=FID, request_id=RID, bucket='portal_service_files', object_path=f'{RID}/{FID}',
           original_name='test.png', content_type='image/png', size_bytes=70,
           status='uploading', created_by=UID, created_at=DATE, updated_at=DATE)
SIGNED = {'signedURL': 'https://example.supabase.co/private?token=temporary'}


def picture(fmt='PNG'):
    b = BytesIO()
    Image.new('RGB', (2, 2)).save(b, format=fmt)
    return b.getvalue()


@pytest.fixture
def sdk(app):
    sdk = MagicMock()
    app.app.dependency_overrides[get_supabase_client] = lambda: sdk
    app.app.dependency_overrides[current_user] = lambda: Principal(id=UID, is_super_admin=True, permissions=[])
    sdk.rpc.return_value.execute.side_effect = [SimpleNamespace(data=ROW), SimpleNamespace(data={**ROW, 'status': 'ready'})]
    sdk.storage.from_.return_value.create_signed_url.return_value = SIGNED
    return sdk


def test_upload_returns_signed_url(client, sdk):
    response = client.post(PATH, headers={'Idempotency-Key': FID},
                           files={'file': ('test.png', picture(), 'application/incorrect')})
    assert response.status_code == 201
    data = response.json()['data']
    assert data['status'] == 'ready'
    assert data['download_url'] == SIGNED['signedURL']
    assert data['expires_in'] == 300
    assert response.headers['cache-control'] == 'no-store'
    first = sdk.rpc.call_args_list[0].args[1]
    assert first['p_data']['content_type'] == 'image/png'
    assert first['p_data']['request_id'] == RID
    assert first['p_actor_id'] == UID
    sdk.storage.from_.return_value.upload.assert_called_once()
    sdk.storage.from_.return_value.create_signed_url.assert_called_once_with(
        ROW['object_path'], 300, {'download': 'test.png'})


def test_retry_completed_file_still_returns_signed_url(client, sdk):
    sdk.rpc.return_value.execute.side_effect = [SimpleNamespace(data={**ROW, 'status': 'ready'})]
    response = client.post(PATH, headers={'Idempotency-Key': FID}, files={'file': ('test.png', picture())})
    assert response.status_code == 201
    assert response.json()['data']['download_url'] == SIGNED['signedURL']
    sdk.storage.from_.return_value.upload.assert_not_called()


@pytest.mark.parametrize('key', [None, 'not-a-uuid'])
def test_requires_idempotency_key(client, sdk, key):
    response = client.post(PATH, headers={} if key is None else {'Idempotency-Key': key},
                           files={'file': ('test.png', picture())})
    assert response.status_code == 422
    sdk.rpc.assert_not_called()


def test_missing_sql_never_writes_storage(client, sdk):
    sdk.rpc.return_value.execute.side_effect = APIError({'message': 'missing', 'code': 'PGRST202', 'hint': None, 'details': None})
    response = client.post(PATH, headers={'Idempotency-Key': FID}, files={'file': ('test.png', picture())})
    assert response.json()['error']['code'] == 'SERVICE_FILES_NOT_INSTALLED'
    sdk.storage.from_.assert_not_called()


def test_storage_failure_retains_retry_reservation(client, sdk):
    sdk.storage.from_.return_value.upload.side_effect = RuntimeError('private key')
    response = client.post(PATH, headers={'Idempotency-Key': FID}, files={'file': ('test.png', picture())})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'UPLOAD_UNCONFIRMED'
    assert sdk.rpc.call_count == 1
    assert 'private key' not in response.text


def test_signing_failure_after_storage_succeeds(client, sdk):
    sdk.storage.from_.return_value.create_signed_url.side_effect = RuntimeError('boom')
    response = client.post(PATH, headers={'Idempotency-Key': FID}, files={'file': ('test.png', picture())})
    assert response.status_code == 503
    assert response.json()['error']['code'] == 'STORAGE_UNAVAILABLE'


@pytest.mark.parametrize('ext,mime', [('xlsx', 'spreadsheetml.sheet'), ('pptx', 'presentationml.presentation'), ('txt', 'text/plain')])
def test_new_file_types_accepted(client, sdk, ext, mime):
    import zipfile
    if ext == 'txt':
        content = b'hello mechanical workshop'
    else:
        from app.services.service_files import OOXML_PARTS
        part, tag, content_type = OOXML_PARTS[f'.{ext}']
        buf = BytesIO()
        with zipfile.ZipFile(buf, 'w') as z:
            z.writestr('[Content_Types].xml',
                f'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
                f'<Override PartName="/{part}" ContentType="{content_type}"/></Types>')
            ns = tag.split('}')[0][1:]
            root = tag.split('}')[1]
            z.writestr(part, f'<?xml version="1.0"?><{root} xmlns="{ns}"></{root}>')
        content = buf.getvalue()
    response = client.post(PATH, headers={'Idempotency-Key': FID}, files={'file': (f'test.{ext}', content)})
    assert response.status_code == 201
    sent_content_type = sdk.rpc.call_args_list[0].args[1]['p_data']['content_type']
    assert mime in sent_content_type


@pytest.mark.parametrize('method,path', [
    ('post', '/service-requests'),
    ('get', '/service-requests'),
    ('get', f'/service-requests/{RID}'),
    ('patch', f'/service-requests/{RID}'),
    ('get', f'/service-requests/{RID}/files'),
    ('post', f'/service-requests/{RID}/files/{FID}/delete'),
    ('get', f'/service-requests/{RID}/files/{FID}/download-url'),
])
def test_permission_denial(app, client, sdk, method, path):
    app.app.dependency_overrides[current_user] = lambda: Principal(id=UID, is_super_admin=False, permissions=['USER_VIEW'])
    kwargs = {'json': {'title': 'x'}} if method in ('post', 'patch') and path == '/service-requests' or \
        (method == 'patch') else {}
    assert getattr(client, method)('/api/v1' + path, **kwargs).status_code == 403
    sdk.rpc.assert_not_called()
    sdk.table.assert_not_called()


def test_mechanical_view_permission_allows_upload(app, client, sdk):
    app.app.dependency_overrides[current_user] = lambda: Principal(id=UID, is_super_admin=False, permissions=['MECHANICAL_VIEW'])
    response = client.post(PATH, headers={'Idempotency-Key': FID}, files={'file': ('test.png', picture())})
    assert response.status_code == 201


def test_create_and_update_request(client, sdk):
    sdk.rpc.return_value.execute.side_effect = [SimpleNamespace(data={
        'id': RID, 'title': 'Sua may', 'status': 'draft', 'created_by': UID, 'updated_by': UID,
        'created_at': DATE, 'updated_at': DATE})]
    response = client.post('/api/v1/service-requests', json={'title': 'Sua may'})
    assert response.status_code == 201
    assert response.json()['data']['title'] == 'Sua may'
    sdk.rpc.return_value.execute.side_effect = [SimpleNamespace(data={
        'id': RID, 'title': 'Sua may', 'status': 'archived', 'created_by': UID, 'updated_by': UID,
        'created_at': DATE, 'updated_at': DATE})]
    response = client.patch(f'/api/v1/service-requests/{RID}', json={'status': 'archived'})
    assert response.status_code == 200
    assert response.json()['data']['status'] == 'archived'


def test_archived_request_blocks_upload(client, sdk):
    sdk.rpc.return_value.execute.side_effect = APIError({'message': 'REQUEST_ARCHIVED', 'code': 'P0001', 'hint': None, 'details': None})
    response = client.post(PATH, headers={'Idempotency-Key': FID}, files={'file': ('test.png', picture())})
    assert response.status_code == 409
    assert response.json()['error']['code'] == 'REQUEST_ARCHIVED'


def test_download_url_refresh(client, sdk, monkeypatch):
    monkeypatch.setattr(ServiceFileRepository, 'one', lambda *a: {**ROW, 'status': 'ready'})
    response = client.get(f'/api/v1/service-requests/{RID}/files/{FID}/download-url')
    assert response.status_code == 200
    assert response.json()['data']['download_url'] == SIGNED['signedURL']
    assert response.json()['data']['expires_in'] == 300


@pytest.mark.parametrize('status', ['uploading', 'deleted'])
def test_unready_file_cannot_get_url(client, sdk, monkeypatch, status):
    monkeypatch.setattr(ServiceFileRepository, 'one', lambda *a: {**ROW, 'status': status})
    response = client.get(f'/api/v1/service-requests/{RID}/files/{FID}/download-url')
    assert response.status_code == 409
    sdk.storage.from_.return_value.create_signed_url.assert_not_called()


def test_download_url_scoped_to_request(client, sdk, monkeypatch):
    other_request = '99999999-9999-4999-8999-999999999999'
    monkeypatch.setattr(ServiceFileRepository, 'one', lambda *a: {**ROW, 'status': 'ready', 'request_id': other_request})
    response = client.get(f'/api/v1/service-requests/{RID}/files/{FID}/download-url')
    assert response.status_code == 404


def test_paginated_files_list(client, sdk, monkeypatch):
    monkeypatch.setattr(ServiceFileRepository, 'one', lambda *a: {'id': RID})
    monkeypatch.setattr(ServiceFileRepository, 'page', lambda *a, **kw: SimpleNamespace(data=[], count=41))
    response = client.get(f'/api/v1/service-requests/{RID}/files?page=2&page_size=20')
    assert response.status_code == 200
    assert response.json()['data']['pagination']['total_pages'] == 3


def test_delete_file(client, sdk):
    sdk.rpc.return_value.execute.side_effect = [SimpleNamespace(data={**ROW, 'status': 'deleted'})]
    response = client.post(f'/api/v1/service-requests/{RID}/files/{FID}/delete')
    assert response.status_code == 200
    assert response.json()['data']['status'] == 'deleted'
    sdk.rpc.assert_called_once_with('portal_service_files_write',
        {'p_actor_id': UID, 'p_action': 'delete_file', 'p_data': {'request_id': RID, 'file_id': FID}})


def test_transport_body_limit(client, sdk):
    response = client.post(PATH, content=b'x' * (11 * 1024 * 1024 + 1), headers={'Origin': 'http://localhost:5173'})
    assert response.status_code == 413
    sdk.rpc.assert_not_called()


def test_cors_upload_key(client):
    response = client.options(PATH, headers={'Origin': 'http://localhost:5173', 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'authorization,idempotency-key,content-type'})
    assert response.status_code == 200


def test_bad_pagination_and_body(client, sdk):
    assert client.get('/api/v1/service-requests?page_size=101').status_code == 422
    assert client.patch(f'/api/v1/service-requests/{RID}', json={}).status_code == 422
    assert client.post('/api/v1/service-requests', json={'title': '   '}).status_code == 422
