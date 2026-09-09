from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError

from app.core.config import Settings
from app.main import create_app
from app.services.supabase import get_auth_client, get_supabase_client

UID = "11111111-1111-4111-8111-111111111111"
PATH = "/api/v1/auth/refresh"


@pytest.fixture
def refresh_clients(app):
    auth, db = MagicMock(), MagicMock()
    auth.auth.refresh_session.return_value = SimpleNamespace(
        user=SimpleNamespace(id=UID, email="user@example.com"),
        session=SimpleNamespace(access_token="new-access", refresh_token="new-refresh",
                                expires_in=3600, expires_at=2000000000),
    )
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": UID, "isActive": True, "is_super_admin": False, "is_first_login": False},
    ]
    db.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.side_effect = [
        SimpleNamespace(data=[{"permissions": {"permission_code": "users.read"}}]), SimpleNamespace(data=[]),
    ]
    app.app.dependency_overrides[get_auth_client] = lambda: auth
    app.app.dependency_overrides[get_supabase_client] = lambda: db
    return auth, db


@pytest.mark.parametrize("admin", [True, False])
def test_refresh_returns_rotated_tokens_and_current_permissions(client, refresh_clients, admin):
    auth, db = refresh_clients
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data[0]["is_super_admin"] = admin
    response = client.post(PATH, json={"refresh_token": "old-refresh"})
    assert response.status_code == 200
    assert response.json()["data"]["refresh_token"] == "new-refresh"
    assert response.json()["data"]["access_token"] == "new-access"
    assert response.json()["data"]["user"]["permissions"] == (["*"] if admin else ["users.read"])
    assert response.headers["cache-control"] == "no-store"
    auth.auth.refresh_session.assert_called_once_with("old-refresh")
    auth.auth.sign_out.assert_not_called()


@pytest.mark.parametrize("body", [
    {}, {"refresh_token": ""}, {"refresh_token": " "}, {"refresh_token": "bad token"},
    {"refresh_token": 123}, {"refresh_token": "x" * 8193},
    {"refresh_token": "private-token", "is_super_admin": True},
])
def test_invalid_body(client, refresh_clients, body):
    response = client.post(PATH, json=body)
    assert response.status_code == 422
    assert "private-token" not in response.text
    refresh_clients[0].auth.refresh_session.assert_not_called()


@pytest.mark.parametrize("exc,status,code", [
    (AuthApiError("private-token", 400, "refresh_token_not_found"), 401, "INVALID_REFRESH_TOKEN"),
    (AuthApiError("private-token", 400, "refresh_token_already_used"), 401, "INVALID_REFRESH_TOKEN"),
    (AuthApiError("private-token", 403, "user_banned"), 401, "INVALID_REFRESH_TOKEN"),
    (AuthApiError("private-token", 429, None), 429, "AUTH_RATE_LIMITED"),
    (AuthApiError("private-token", 500, None), 503, "REFRESH_UNAVAILABLE"),
    (httpx.ReadTimeout("private-token"), 503, "REFRESH_UNAVAILABLE"),
])
def test_refresh_errors(client, refresh_clients, exc, status, code):
    auth, db = refresh_clients
    auth.auth.refresh_session.side_effect = exc
    response = client.post(PATH, json={"refresh_token": "private-token"})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private-token" not in response.text
    db.table.assert_not_called()
    auth.auth.refresh_session.assert_called_once()


def test_missing_profile(client, refresh_clients):
    refresh_clients[1].table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    response = client.post(PATH, json={"refresh_token": "old"})
    assert response.status_code == 403
    assert "new-access" not in response.text


def test_profile_failure_after_rotation(client, refresh_clients):
    refresh_clients[1].table.side_effect = RuntimeError("private-token")
    response = client.post(PATH, json={"refresh_token": "old"})
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REFRESH_PROFILE_UNAVAILABLE"
    assert "new-refresh" not in response.text


def test_missing_session(client, refresh_clients):
    refresh_clients[0].auth.refresh_session.return_value.session = None
    assert client.post(PATH, json={"refresh_token": "old"}).status_code == 503
    refresh_clients[1].table.assert_not_called()


def test_real_sdk_refresh_grant_and_client_isolation(monkeypatch):
    import json
    import app.services.supabase as service
    original = httpx.Client
    calls = []
    def handle(request):
        calls.append(request)
        if request.url.path == "/auth/v1/token":
            assert request.url.params["grant_type"] == "refresh_token"
            assert json.loads(request.content)["refresh_token"] == "old-refresh"
            return httpx.Response(200, json={
                "access_token": "new-access", "refresh_token": "new-refresh",
                "token_type": "bearer", "expires_in": 3600,
                "user": {"id": UID, "isActive": True, "email": "user@example.com", "aud": "authenticated",
                         "created_at": "2026-01-01T00:00:00Z", "app_metadata": {}, "user_metadata": {}},
            })
        assert request.url.path == "/rest/v1/profiles"
        assert request.headers["authorization"] == "Bearer test-service-key"
        assert request.url.params["id"] == f"eq.{UID}"
        return httpx.Response(200, json=[{"id": UID, "isActive": True, "is_super_admin": True, "is_first_login": False}])
    monkeypatch.setattr(service.httpx, "Client", lambda **kw: original(
        transport=httpx.MockTransport(handle), **kw,
    ))
    app = create_app(Settings(_env_file=None, supabase_url="https://example.supabase.co",
                             supabase_service_role_key="test-service-key", cors_origins=""))
    with TestClient(app) as client:
        response = client.post(PATH, json={"refresh_token": "old-refresh"})
    assert response.status_code == 200
    assert response.json()["data"]["refresh_token"] == "new-refresh"
    assert len(calls) == 2

