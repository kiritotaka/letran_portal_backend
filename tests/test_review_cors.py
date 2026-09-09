from fastapi.testclient import TestClient
from app.main import create_app
from app.core.config import Settings


def test_review_put_preflight():
    app=create_app(Settings(_env_file=None,cors_origins='http://localhost:3000'))
    with TestClient(app) as client:
        response=client.options('/api/v1/document-requests/22222222-2222-4222-8222-222222222222/review',headers={
            'Origin':'http://localhost:3000','Access-Control-Request-Method':'PUT',
            'Access-Control-Request-Headers':'authorization,content-type,idempotency-key'})
        assert response.status_code==200
        assert response.headers['access-control-allow-origin']=='http://localhost:3000'
        assert 'PUT' in response.headers['access-control-allow-methods']
        assert 'idempotency-key' in response.headers['access-control-allow-headers'].lower()
        denied=client.options('/api/v1/document-requests/22222222-2222-4222-8222-222222222222/review',headers={
            'Origin':'https://untrusted.example','Access-Control-Request-Method':'PUT'})
        assert denied.status_code==400
        assert 'access-control-allow-origin' not in denied.headers
