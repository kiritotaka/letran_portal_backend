from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from app.services.supabase import get_supabase_client


def test_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "letran-portal-backend"}


def test_missing_supabase(client):
    response = client.get("/api/v1/health/supabase")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "SUPABASE_NOT_CONFIGURED"


@pytest.mark.parametrize("failure", [None, RuntimeError("private-secret"), httpx.ReadTimeout("private-secret")])
def test_supabase_probe(app, client, failure):
    sdk = MagicMock()
    query = sdk.table.return_value.select.return_value.limit.return_value
    query.execute.side_effect = failure
    app.app.dependency_overrides[get_supabase_client] = lambda: sdk
    response = client.get("/api/v1/health/supabase")
    assert response.status_code == (503 if failure else 200)
    assert "private-secret" not in response.text
    sdk.table.assert_called_once_with("profiles")
    sdk.table.return_value.select.assert_called_once_with("*", head=True)
    sdk.table.return_value.select.return_value.limit.assert_called_once_with(1)


def test_real_sdk_with_mock_transport(monkeypatch):
    import app.services.supabase as service
    original_client = httpx.Client
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, headers={"content-range": "0-0/*"})

    monkeypatch.setattr(service.httpx, "Client", lambda **kw: original_client(
        transport=httpx.MockTransport(handler), **kw,
    ))
    app = create_app(Settings(
        _env_file=None, supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-only-key", gemini_api_key="", cors_origins="",
    ))
    with TestClient(app) as client:
        assert client.get("/api/v1/health/supabase").status_code == 200
    assert len(requests) == 1
    assert requests[0].method == "HEAD"
    assert requests[0].url.path == "/rest/v1/profiles"
    assert requests[0].url.params["limit"] == "1"


def test_cors(client):
    allowed = client.options("/api/v1/health", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET",
    })
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == "http://localhost:5173"
    denied = client.options("/api/v1/health", headers={
        "Origin": "https://untrusted.example", "Access-Control-Request-Method": "GET",
    })
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers


def test_not_found(client):
    response = client.get("/missing")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "HTTP_404"


def test_unexpected_error_is_safe_and_has_cors(app, client):
    @app.app.get("/crash")
    def crash():
        raise RuntimeError("private-secret")

    response = client.get("/crash", headers={"Origin": "http://localhost:5173"})
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "INTERNAL_ERROR"
    assert "private-secret" not in response.text
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_validation_error_is_safe(app, client):
    @app.app.get("/number")
    def number(value: int):
        return value

    response = client.get("/number?value=private-secret")
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert "private-secret" not in response.text

