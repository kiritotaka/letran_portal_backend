from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from postgrest.exceptions import APIError
from supabase_auth.errors import AuthApiError

from app.dependencies.auth import Principal, current_user
from app.services.supabase import get_auth_client, get_supabase_client

ACTOR = "11111111-1111-4111-8111-111111111111"
TARGET = "22222222-2222-4222-8222-222222222222"
CREATE = {"email": "new@example.com", "password": "TemporaryPassword123!", "permission_ids": [1, 2]}
ROW = {"id": TARGET, "email": "new@example.com", "is_active": True,
       "is_super_admin": False, "is_first_login": True, "permissions": ["USER_VIEW"]}


@pytest.fixture
def sdk(app):
    sdk = MagicMock()
    app.app.dependency_overrides[get_supabase_client] = lambda: sdk
    app.app.dependency_overrides[current_user] = lambda: Principal(id=ACTOR, is_super_admin=True, permissions=[])
    sdk.rpc.return_value.execute.return_value.data = ROW
    sdk.auth.admin.create_user.return_value = SimpleNamespace(user=SimpleNamespace(id=TARGET))
    return sdk


def test_create_banned_until_permissions_saved(client, sdk):
    events = []
    def rpc(name, values):
        events.append("validate" if values["p_validate_only"] else "save")
        assert values["p_actor_id"] == ACTOR
        assert values["p_permission_ids"] == [1, 2]
        return SimpleNamespace(execute=lambda: SimpleNamespace(data=ROW))
    sdk.rpc.side_effect = rpc
    def create(values):
        assert values["ban_duration"] == "876000h"
        assert values["email_confirm"] is True
        events.append("auth-create")
        return SimpleNamespace(user=SimpleNamespace(id=TARGET))
    sdk.auth.admin.create_user.side_effect = create
    sdk.auth.admin.update_user_by_id.side_effect = lambda *args: events.append("activate")
    response = client.post("/api/v1/users", json=CREATE)
    assert response.status_code == 201
    assert events == ["validate", "auth-create", "save", "activate"]
    assert response.json()["data"]["is_first_login"] is True
    assert "password" not in response.text
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("payload", [{}, {"permission_ids": None}, {"permission_ids": [True]},
    {"permission_ids": [-1]}, {"is_active": "false"}, {"password": "cannot-reset-here"}])
def test_patch_validation(client, sdk, payload):
    assert client.patch(f"/api/v1/users/{TARGET}", json=payload).status_code == 422
    sdk.rpc.assert_not_called()


def test_clear_permissions_and_patch_omitted_fields(client, sdk):
    assert client.patch(f"/api/v1/users/{TARGET}", json={"permission_ids": []}).status_code == 200
    values = sdk.rpc.call_args.args[1]
    assert values["p_permission_ids"] == []
    assert "p_email" not in values and "p_is_super_admin" not in values
    sdk.auth.admin.update_user_by_id.assert_not_called()


@pytest.mark.parametrize("method,path,code", [
    ("post", "/users", "USER_CREATE"), ("patch", f"/users/{TARGET}", "USER_UPDATE"),
    ("post", f"/users/{TARGET}/deactivate", "USER_REMOVE")])
def test_route_permissions(app, client, sdk, method, path, code):
    app.app.dependency_overrides[current_user] = lambda: Principal(id=ACTOR, is_super_admin=False, permissions=["USER_VIEW"])
    assert getattr(client, method)("/api/v1"+path, json=CREATE).status_code == 403
    sdk.rpc.assert_not_called()


@pytest.mark.parametrize("message,code,status", [
    ("missing", "PGRST202", 503), ("FORBIDDEN", "P0001", 403),
    ("INVALID_PERMISSION_IDS", "P0001", 422), ("EMAIL_ALREADY_EXISTS", "P0001", 409),
    ("USER_NOT_FOUND", "P0001", 404), ("SELF_UPDATE_FORBIDDEN", "P0001", 403)])
def test_preflight_errors_never_create_auth(client, sdk, message, code, status):
    sdk.rpc.return_value.execute.side_effect = APIError({"message": message, "code": code, "details": None, "hint": None})
    response = client.post("/api/v1/users", json=CREATE)
    assert response.status_code == status
    sdk.auth.admin.create_user.assert_not_called()


def test_provisioning_failure_keeps_auth_banned(client, sdk):
    sdk.rpc.return_value.execute.side_effect = [SimpleNamespace(data={"validated": True}), RuntimeError("private-error")]
    response = client.post("/api/v1/users", json=CREATE)
    assert response.json()["error"]["code"] == "USER_PROVISIONING_INCOMPLETE"
    sdk.auth.admin.update_user_by_id.assert_not_called()
    sdk.auth.admin.delete_user.assert_not_called()
    assert "private-error" not in response.text


def test_deactivate_saves_before_auth_ban_failure(client, sdk):
    sdk.auth.admin.update_user_by_id.side_effect = RuntimeError("private-error")
    response = client.post(f"/api/v1/users/{TARGET}/deactivate")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "USER_AUTH_SYNC_INCOMPLETE"
    assert sdk.rpc.call_args.args[1]["p_action"] == "deactivate"
    sdk.auth.admin.update_user_by_id.assert_called_once_with(TARGET, {"ban_duration": "876000h"})


def test_email_partial_failure_is_explicit(client, sdk):
    sdk.rpc.return_value.execute.side_effect = [SimpleNamespace(data={}), RuntimeError()]
    response = client.patch(f"/api/v1/users/{TARGET}", json={"email": "changed@example.com"})
    assert response.json()["error"]["code"] == "USER_EMAIL_SYNC_INCOMPLETE"
    sdk.auth.admin.update_user_by_id.assert_called_once_with(TARGET, {"email": "changed@example.com", "email_confirm": True})


@pytest.mark.parametrize("active", [False, None, "missing"])
@pytest.mark.parametrize("endpoint,payload", [
    ("/auth/login", {"email": "user@example.com", "password": "password"}),
    ("/auth/refresh", {"refresh_token": "token"}),
    ("/auth/change-password", {"email": "user@example.com", "current_password": "password", "new_password": "NewPassword123"}),
    ("/users", None),
])
def test_inactive_blocks_all_auth_paths(app, client, active, endpoint, payload):
    sdk = MagicMock()
    session = SimpleNamespace(user=SimpleNamespace(id=ACTOR), session=SimpleNamespace())
    sdk.auth.sign_in_with_password.return_value = session
    sdk.auth.refresh_session.return_value = session
    sdk.auth.get_user.return_value = session
    profile = {"id": ACTOR, "is_super_admin": True, "is_first_login": False}
    if active != "missing":
        profile["isActive"] = active
    sdk.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [profile]
    app.app.dependency_overrides[get_supabase_client] = lambda: sdk
    app.app.dependency_overrides[get_auth_client] = lambda: sdk
    if payload is None:
        response = client.get("/api/v1"+endpoint, headers={"Authorization": "Bearer test"})
    else:
        response = client.post("/api/v1"+endpoint, json=payload)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ACCOUNT_INACTIVE"
    sdk.auth.update_user.assert_not_called()


def test_patch_cors(client):
    response = client.options("/api/v1/users/"+TARGET, headers={
        "Origin": "http://localhost:5173", "Access-Control-Request-Method": "PATCH",
        "Access-Control-Request-Headers": "authorization,content-type"})
    assert response.status_code == 200


def test_real_sdk_create_and_rpc_transport(monkeypatch):
    import json
    import httpx
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.main import create_app
    import app.services.supabase as service

    original = httpx.Client
    seen = []
    def handle(request):
        assert request.headers["authorization"] == "Bearer test-service-key"
        body = json.loads(request.content)
        seen.append((request.method, request.url.path, body))
        if request.url.path == "/rest/v1/rpc/portal_manage_user":
            assert body["p_actor_id"] == ACTOR
            return httpx.Response(200, json={"validated": True} if body["p_validate_only"] else ROW)
        assert request.url.path in {"/auth/v1/admin/users", "/auth/v1/admin/users/"+TARGET}
        return httpx.Response(200, json={"id": TARGET, "email": "new@example.com",
            "aud": "authenticated", "created_at": "2026-01-01T00:00:00Z",
            "app_metadata": {}, "user_metadata": {}})

    monkeypatch.setattr(service.httpx, "Client", lambda **kw: original(transport=httpx.MockTransport(handle), **kw))
    application = create_app(Settings(_env_file=None, supabase_url="https://example.supabase.co",
        supabase_service_role_key="test-service-key", cors_origins=""))
    application.app.dependency_overrides[current_user] = lambda: Principal(id=ACTOR, is_super_admin=True, permissions=[])
    with TestClient(application) as client:
        response = client.post("/api/v1/users", json=CREATE)
    assert response.status_code == 201
    assert [item[0] for item in seen] == ["POST", "POST", "POST", "PUT"]
    assert seen[1][2]["ban_duration"] == "876000h"
    assert seen[3][2] == {"ban_duration": "none"}
