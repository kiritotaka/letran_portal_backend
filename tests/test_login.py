from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError

from app.core.config import Settings
from app.main import create_app
from app.services.supabase import get_auth_client, get_supabase_client

USER_ID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def login_clients(app):
    auth = MagicMock()
    db = MagicMock()
    auth.auth.sign_in_with_password.return_value = SimpleNamespace(
        user=SimpleNamespace(id=USER_ID, email="user@example.com"),
        session=SimpleNamespace(access_token="test-access", refresh_token="test-refresh",
                                expires_in=3600, expires_at=2000000000),
    )
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [{
        "id": USER_ID, "email": "user@example.com", "is_super_admin": False, "is_first_login": True,
    }]
    db.table.return_value.select.return_value.eq.return_value.order.return_value.range.return_value.execute.side_effect = [
        SimpleNamespace(data=[{"permissions": {"permission_code": "users.read"}}]),
        SimpleNamespace(data=[]),
    ]
    app.app.dependency_overrides[get_auth_client] = lambda: auth
    app.app.dependency_overrides[get_supabase_client] = lambda: db
    return auth, db


def test_login(client, login_clients):
    response = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": " password "})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["user"]["permissions"] == ["users.read"]
    assert data["user"]["is_first_login"] is True
    assert data["access_token"] == "test-access"
    assert response.headers["cache-control"] == "no-store"
    login_clients[0].auth.sign_in_with_password.assert_called_once_with({
        "email": "user@example.com", "password": " password ",
    })


def test_admin(client, login_clients):
    db = login_clients[1]
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data[0]["is_super_admin"] = True
    response = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "pass"})
    assert response.json()["data"]["user"]["permissions"] == ["*"]
    db.table.assert_called_once_with("profiles")


@pytest.mark.parametrize("body", [
    {}, {"email": "bad", "password": "private-password"},
    {"email": "user@example.com", "password": ""},
    {"email": "user@example.com", "password": "pass", "is_super_admin": True},
])
def test_invalid_request(client, login_clients, body):
    response = client.post("/api/v1/auth/login", json=body)
    assert response.status_code == 422
    assert "private-password" not in response.text
    login_clients[0].auth.sign_in_with_password.assert_not_called()


@pytest.mark.parametrize("exception,status,code", [
    (AuthApiError("private-upstream", 400, "invalid_credentials"), 401, "INVALID_CREDENTIALS"),
    (AuthApiError("private-upstream", 400, "email_not_confirmed"), 401, "INVALID_CREDENTIALS"),
    (AuthApiError("private-upstream", 429, "over_request_rate_limit"), 429, "AUTH_RATE_LIMITED"),
    (AuthApiError("private-upstream", 500, None), 503, "AUTH_UNAVAILABLE"),
    (httpx.ReadTimeout("private-upstream"), 503, "AUTH_UNAVAILABLE"),
])
def test_auth_errors(client, login_clients, exception, status, code):
    login_clients[0].auth.sign_in_with_password.side_effect = exception
    response = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "pass"})
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private-upstream" not in response.text
    login_clients[1].table.assert_not_called()


def test_missing_profile(client, login_clients):
    login_clients[1].table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = []
    response = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "pass"})
    assert response.status_code == 403
    assert "test-access" not in response.text


def test_profile_failure(client, login_clients):
    login_clients[1].table.side_effect = RuntimeError("private-upstream")
    response = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "pass"})
    assert response.status_code == 503
    assert "test-access" not in response.text


def test_login_cors(client):
    response = client.options("/api/v1/auth/login", headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type",
    })
    assert response.status_code == 200


def test_sdk_auth_and_data_clients_are_isolated(monkeypatch):
    import app.services.supabase as service
    original_client = httpx.Client
    seen = []
    def handle(request):
        seen.append(request)
        if request.url.path == "/auth/v1/token":
            return httpx.Response(200, json={
                "access_token": "user-access-token", "refresh_token": "user-refresh-token",
                "token_type": "bearer", "expires_in": 3600,
                "user": {"id": USER_ID, "email": "user@example.com", "aud": "authenticated",
                         "created_at": "2026-01-01T00:00:00Z", "app_metadata": {}, "user_metadata": {}},
            })
        if request.url.path == "/rest/v1/profiles":
            assert request.headers["authorization"] == "Bearer test-service-key"
            return httpx.Response(200, json=[{
                "id": USER_ID, "email": "user@example.com",
                "is_super_admin": True, "is_first_login": False,
            }])
        raise AssertionError("Unexpected upstream request")
    monkeypatch.setattr(service.httpx, "Client", lambda **kw: original_client(
        transport=httpx.MockTransport(handle), **kw,
    ))
    app = create_app(Settings(_env_file=None, supabase_url="https://example.supabase.co",
                             supabase_service_role_key="test-service-key", cors_origins=""))
    with TestClient(app) as client:
        response = client.post("/api/v1/auth/login", json={"email": "user@example.com", "password": "pass"})
    assert response.status_code == 200
    assert len(seen) == 2

