import json
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
BODY = {"email": "user@example.com", "current_password": "Old-password1!", "new_password": "New-password2!"}
REGULAR = "/api/v1/auth/change-password"
FIRST = "/api/v1/auth/change-password-first-login"


@pytest.fixture
def password_clients(app):
    auth, db = MagicMock(), MagicMock()
    auth.auth.sign_in_with_password.return_value = SimpleNamespace(
        user=SimpleNamespace(id=UID), session=SimpleNamespace(access_token="private-token"),
    )
    auth.auth.update_user.return_value = SimpleNamespace(user=SimpleNamespace(id=UID))
    db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": UID, "isActive": True, "is_first_login": True, "is_super_admin": False},
    ]
    db.table.return_value.update.return_value.eq.return_value.execute.return_value.data = [
        {"id": UID, "isActive": True, "is_first_login": False},
    ]
    app.app.dependency_overrides[get_auth_client] = lambda: auth
    app.app.dependency_overrides[get_supabase_client] = lambda: db
    return auth, db


@pytest.mark.parametrize("path", [REGULAR, FIRST])
@pytest.mark.parametrize("camel", [True, False])
def test_change_success(client, password_clients, path, camel):
    auth, db = password_clients
    body = BODY if not camel else {
        "email": BODY["email"], "currentPassword": BODY["current_password"], "newPassword": BODY["new_password"],
    }
    response = client.post(path, json=body)
    assert response.status_code == 200
    assert response.json()["data"] == {
        "password_changed": True, "is_first_login": False, "requires_login": True,
    }
    assert response.headers["cache-control"] == "no-store"
    assert BODY["new_password"] not in response.text
    auth.auth.sign_in_with_password.assert_called_once_with({
        "email": BODY["email"], "password": BODY["current_password"],
    })
    auth.auth.update_user.assert_called_once_with({"password": BODY["new_password"]})
    values = db.table.return_value.update.call_args.args[0]
    assert set(values) == {"is_first_login", "updated_by", "updated_at"}
    assert values["updated_by"] == UID
    assert values["is_first_login"] is False
    db.table.return_value.update.return_value.eq.assert_called_once_with("id", UID)
    auth.auth.admin.update_user_by_id.assert_not_called()
    auth.auth.sign_out.assert_called_once_with({"scope": "local"})


@pytest.mark.parametrize("field,value", [
    ("email", "bad"), ("current_password", ""), ("new_password", "short"),
    ("new_password", " " * 8), ("new_password", BODY["current_password"]),
    ("new_password", "x" * 4097), ("user_id", "someone-else"),
    ("is_super_admin", True), ("currentPassword", "ambiguous-alias"),
])
def test_invalid_request_does_not_call_auth(client, password_clients, field, value):
    response = client.post(REGULAR, json={**BODY, field: value})
    assert response.status_code == 422
    password_clients[0].auth.sign_in_with_password.assert_not_called()
    assert BODY["current_password"] not in response.text
    assert BODY["new_password"] not in response.text


def test_wrong_password_blocks_all_writes(client, password_clients):
    auth, db = password_clients
    auth.auth.sign_in_with_password.side_effect = AuthApiError("private-message", 400, "invalid_credentials")
    response = client.post(FIRST, json=BODY)
    assert response.status_code == 401
    assert "private-message" not in response.text
    auth.auth.update_user.assert_not_called()
    db.table.assert_not_called()


@pytest.mark.parametrize("missing", [False, True])
def test_profile_precondition_blocks_password_write(client, password_clients, missing):
    auth, db = password_clients
    query = db.table.return_value.select.return_value.eq.return_value.limit.return_value.execute
    query.return_value.data = [] if missing else [{"id": UID, "isActive": True, "is_first_login": False}]
    response = client.post(FIRST, json=BODY)
    assert response.status_code == (403 if missing else 409)
    auth.auth.update_user.assert_not_called()
    db.table.return_value.update.assert_not_called()
    auth.auth.sign_out.assert_called_once()


def test_regular_change_allows_completed_first_login(client, password_clients):
    password_clients[1].table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": UID, "isActive": True, "is_first_login": False},
    ]
    assert client.post(REGULAR, json=BODY).status_code == 200


@pytest.mark.parametrize("exc,status,code", [
    (AuthApiError("private-message", 422, "weak_password"), 422, "PASSWORD_POLICY_VIOLATION"),
    (AuthApiError("private-message", 422, "same_password"), 422, "PASSWORD_POLICY_VIOLATION"),
    (AuthApiError("private-message", 403, "insufficient_aal"), 403, "REAUTHENTICATION_REQUIRED"),
    (AuthApiError("private-message", 401, None), 401, "INVALID_SESSION"),
    (AuthApiError("private-message", 429, None), 429, "AUTH_RATE_LIMITED"),
    (AuthApiError("private-message", 500, None), 503, "PASSWORD_CHANGE_STATUS_UNKNOWN"),
    (httpx.ReadTimeout("private-message"), 503, "PASSWORD_CHANGE_STATUS_UNKNOWN"),
])
def test_update_error_never_clears_flag(client, password_clients, exc, status, code):
    auth, db = password_clients
    auth.auth.update_user.side_effect = exc
    response = client.post(FIRST, json=BODY)
    assert response.status_code == status
    assert response.json()["error"]["code"] == code
    assert "private-message" not in response.text
    db.table.return_value.update.assert_not_called()
    auth.auth.sign_out.assert_called_once()


@pytest.mark.parametrize("empty_result", [True, False])
def test_partial_success_is_explicit(client, password_clients, empty_result):
    auth, db = password_clients
    query = db.table.return_value.update.return_value.eq.return_value.execute
    if empty_result:
        query.return_value.data = []
    else:
        query.side_effect = httpx.ReadTimeout("private-message")
    response = client.post(FIRST, json=BODY)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "PASSWORD_CHANGED_PROFILE_SYNC_FAILED"
    auth.auth.update_user.assert_called_once()
    assert "private-message" not in response.text


def test_profile_read_failure_does_not_change_password(client, password_clients):
    password_clients[1].table.side_effect = RuntimeError("private-message")
    response = client.post(FIRST, json=BODY)
    assert response.status_code == 503
    password_clients[0].auth.update_user.assert_not_called()


def test_cleanup_failure_does_not_hide_success(client, password_clients, caplog):
    password_clients[0].auth.sign_out.side_effect = RuntimeError("private-message")
    response = client.post(FIRST, json=BODY)
    assert response.status_code == 200
    assert "private-message" not in caplog.text


def test_real_sdk_request_order_identity_and_credentials(monkeypatch):
    import app.services.supabase as service
    original = httpx.Client
    calls = []
    auth_user = {"id": UID, "isActive": True, "email": BODY["email"], "aud": "authenticated",
                 "created_at": "2026-01-01T00:00:00Z", "app_metadata": {}, "user_metadata": {}}
    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.path == "/auth/v1/token":
            body = json.loads(request.content)
            assert body["password"] == BODY["current_password"]
            return httpx.Response(200, json={
                "access_token": "user-access", "refresh_token": "user-refresh",
                "token_type": "bearer", "expires_in": 3600, "user": auth_user,
            })
        if request.url.path == "/auth/v1/user":
            assert request.method == "PUT"
            assert request.headers["authorization"] == "Bearer user-access"
            assert json.loads(request.content) == {"password": BODY["new_password"]}
            return httpx.Response(200, json=auth_user)
        if request.url.path == "/auth/v1/logout":
            assert request.url.params["scope"] == "local"
            return httpx.Response(204)
        if request.url.path == "/rest/v1/profiles":
            assert request.headers["authorization"] == "Bearer test-service-key"
            assert request.url.params["id"] == f"eq.{UID}"
            if request.method == "GET":
                return httpx.Response(200, json=[{"id": UID, "isActive": True, "is_first_login": True}])
            assert request.method == "PATCH"
            values = json.loads(request.content)
            assert values["updated_by"] == UID
            assert values["is_first_login"] is False
            return httpx.Response(200, json=[{"id": UID, "isActive": True, "is_first_login": False}])
        raise AssertionError("Unexpected request")
    monkeypatch.setattr(service.httpx, "Client", lambda **kw: original(
        transport=httpx.MockTransport(handle), **kw,
    ))
    app = create_app(Settings(_env_file=None, supabase_url="https://example.supabase.co",
                             supabase_service_role_key="test-service-key", cors_origins=""))
    with TestClient(app) as client:
        response = client.post(FIRST, json=BODY)
    assert response.status_code == 200
    assert calls == [
        ("POST", "/auth/v1/token"), ("GET", "/rest/v1/profiles"),
        ("PUT", "/auth/v1/user"), ("PATCH", "/rest/v1/profiles"), ("POST", "/auth/v1/logout"),
    ]

