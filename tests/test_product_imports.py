import hashlib
from io import BytesIO
from threading import Event
from unittest.mock import MagicMock

import pytest
from openpyxl import Workbook
from app.dependencies.auth import Principal, current_user
from app.repositories.product_imports import ProductImportRepository
from app.services.product_import_parser import ImportFailure, parse_products
from app.services.product_import_worker import process_import
from app.services.supabase import get_supabase_client

UID = '11111111-1111-4111-8111-111111111111'
FID = '22222222-2222-4222-8222-222222222222'
JID = '33333333-3333-4333-8333-333333333333'


def csv_bytes(lines):
    return ('Mã TP/BTP,Tên TP/BTP\n' + lines).encode('utf-8-sig')


def xlsx_bytes(rows, second_sheet=False):
    book = Workbook()
    for row in rows:
        book.active.append(row)
    if second_sheet:
        book.create_sheet('Other')
    output = BytesIO()
    book.save(output)
    book.close()
    return output.getvalue()


def test_dedup_preserves_text_codes_and_reports_conflicts():
    result = parse_products('p.csv', csv_bytes('001,Chair\n001,Chair\nA,Table\nA,Other\nB,\n'))
    assert result['summary']['source_rows'] == 5
    assert result['summary']['duplicate_rows'] == 1
    assert result['rows'][0]['product_code'] == '001'
    assert result['rows'][0]['occurrences'] == 2
    assert result['rows'][1]['error_code'] == 'CONFLICTING_PRODUCT_NAME'
    assert sum(bool(r['error_code']) for r in result['rows']) == 3


def test_erp_header_offset_and_total():
    content = xlsx_bytes([['Export'], [], [], ['Mã TP/BTP', 'Tên TP/BTP', 'Qty'],
                          [' A ', ' Chair ', 2], ['A', 'Chair', 3], [None, None, 5]])
    result = parse_products('p.xlsx', content)
    assert result['rows'] == [{'source_row': 5, 'product_code': 'A', 'product_name': 'Chair',
                              'occurrences': 2, 'error_code': None}]
    assert result['summary']['ignored_rows'] == 1


def test_formulas_numeric_codes_missing_names_are_not_inferred():
    content = xlsx_bytes([['Mã TP/BTP', 'Tên TP/BTP'], [123, 'Chair'], ['A', '=1+1'], ['B', None]])
    result = parse_products('p.xlsx', content)
    assert [r['error_code'] for r in result['rows']] == [
        'INVALID_PRODUCT_CODE', 'FORMULA_OR_CELL_ERROR', 'INVALID_PRODUCT_NAME']


def test_sheet_selection_and_wrong_headers():
    content = xlsx_bytes([['Mã TP/BTP', 'Tên TP/BTP'], ['A', 'Chair']], True)
    with pytest.raises(ImportFailure) as exc:
        parse_products('p.xlsx', content)
    assert exc.value.code == 'IMPORT_SHEET_REQUIRED'
    assert parse_products('p.xlsx', content, 'Sheet')['rows'][0]['product_code'] == 'A'
    with pytest.raises(ImportFailure) as exc:
        parse_products('p.csv', b'wrong,headers\nA,B')
    assert exc.value.code == 'IMPORT_HEADERS_NOT_FOUND'


def test_import_limit_and_checkpoint():
    checkpoint = MagicMock()
    parse_products('p.csv', csv_bytes('A,Chair\n' * 1000), checkpoint=checkpoint)
    assert checkpoint.call_count == 2
    with pytest.raises(ImportFailure) as exc:
        parse_products('p.csv', csv_bytes(''.join(f'{i},Name\n' for i in range(10001))))
    assert exc.value.code == 'IMPORT_PREVIEW_LIMIT'


def test_worker_checks_hash_and_finishes_only_preview(monkeypatch):
    client = MagicMock()
    content = csv_bytes('A,Chair\n')
    client.storage.from_.return_value.download.return_value = content
    job = {'id': JID, 'lease_token': UID, 'sheet_name': None, 'source': {
        'bucket': 'portal_uploads', 'object_path': 'p', 'original_name': 'p.csv',
        'size_bytes': len(content), 'sha256': hashlib.sha256(content).hexdigest()}}
    calls = []
    monkeypatch.setattr(ProductImportRepository, 'worker', lambda self, *args: calls.append(args) or {'ok': True})
    process_import(client, job, Event())
    assert calls[0][0] == 'finish' and calls[0][2]['rows'][0]['product_code'] == 'A'
    client.table.assert_not_called()
    calls.clear()
    job['source']['sha256'] = '0' * 64
    process_import(client, job, Event())
    assert calls[0][0] == 'fail' and calls[0][2]['error_code'] == 'IMPORT_SOURCE_CHANGED'
    calls.clear()
    stop = Event()
    stop.set()
    process_import(client, job, stop)
    assert calls == []


def test_api_permission_validation_and_contract(app, client, monkeypatch):
    sdk = MagicMock()
    app.app.dependency_overrides[get_supabase_client] = lambda: sdk
    actor = Principal(id=UID, is_super_admin=False, permissions=['PRODUCT_IMPORT'])
    app.app.dependency_overrides[current_user] = lambda: actor
    row = {'id': JID, 'file_id': FID, 'sheet_name': None, 'status': 'queued', 'attempts': 0,
           'summary': {}, 'error_code': None, 'created_by': UID,
           'created_at': '2026-09-16T00:00:00Z', 'updated_at': '2026-09-16T00:00:00Z', 'finished_at': None}
    monkeypatch.setattr(ProductImportRepository, 'action', lambda *a: row)
    r = client.post('/api/v1/product-imports', json={'file_id': FID}, headers={'Idempotency-Key': JID})
    assert r.status_code == 202 and r.json()['data']['status'] == 'queued'
    assert r.headers['cache-control'] == 'no-store'
    assert client.get('/api/v1/product-imports/' + JID).status_code == 200
    assert client.get('/api/v1/product-imports/' + JID + '/rows?page_size=101').status_code == 422
    assert client.post('/api/v1/product-imports', json={'file_id': FID}).status_code == 422
    actor.permissions = ['PRODUCT_VIEW']
    assert client.get('/api/v1/product-imports/' + JID).status_code == 403
