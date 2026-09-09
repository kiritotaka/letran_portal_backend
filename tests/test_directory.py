from types import SimpleNamespace
from unittest.mock import MagicMock
import httpx
import pytest
from fastapi.testclient import TestClient
from supabase_auth.errors import AuthApiError
from app.dependencies.auth import Principal, current_user
from app.main import create_app
from app.core.config import Settings
from app.repositories.directory import DirectoryRepository
from app.services.supabase import get_supabase_client

UID = "11111111-1111-4111-8111-111111111111"


@pytest.fixture
def sdk(app):
    client = MagicMock()
    app.app.dependency_overrides[get_supabase_client] = lambda: client
    client.auth.get_user.return_value = SimpleNamespace(user=SimpleNamespace(id=UID))
    client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
        {"id": UID, "is_super_admin": True, "is_first_login": False},
    ]
    return client


@pytest.mark.parametrize("path", ["/users", "/permissions"])
def test_no_token(client, sdk, path):
    assert client.get("/api/v1"+path).status_code == 401
    sdk.auth.get_user.assert_not_called()


def test_invalid_token(client, sdk):
    sdk.auth.get_user.side_effect = AuthApiError("private-token", 401, "bad_jwt")
    response = client.get("/api/v1/users", headers={"Authorization": "Bearer fake"})
    assert response.status_code == 401
    assert "private-token" not in response.text
    sdk.table.assert_not_called()


def test_first_login_blocks_admin(client, sdk):
    sdk.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data[0]["is_first_login"] = True
    response = client.get("/api/v1/users", headers={"Authorization": "Bearer fake"})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "PASSWORD_CHANGE_REQUIRED"


@pytest.mark.parametrize("path,codes,allowed", [
    ("/users", ["USER_VIEW"], True), ("/users", ["USER_CREATE"], False),
    ("/permissions", ["USER_CREATE"], True), ("/permissions", ["USER_UPDATE"], True),
    ("/permissions", ["PERM_VIEW"], True), ("/permissions", ["USER_VIEW"], False),
    ("/users", ["*"], False),
])
def test_permission_matrix(app, client, sdk, monkeypatch, path, codes, allowed):
    app.app.dependency_overrides[current_user] = lambda: Principal(id=UID, is_super_admin=False, permissions=codes)
    monkeypatch.setattr(DirectoryRepository, "users", lambda *a: SimpleNamespace(data=[], count=0))
    monkeypatch.setattr(DirectoryRepository, "permissions", lambda *a: SimpleNamespace(data=[], count=0))
    monkeypatch.setattr(DirectoryRepository, "assigned_permissions", lambda *a: {})
    response = client.get("/api/v1"+path)
    assert response.status_code == (200 if allowed else 403)


@pytest.mark.parametrize("query", ["page=0", "page_size=0", "page_size=101", "page=abc"])
def test_invalid_pagination(app, client, sdk, query):
    app.app.dependency_overrides[current_user] = lambda: Principal(id=UID, is_super_admin=True, permissions=[])
    assert client.get("/api/v1/users?"+query).status_code == 422


def test_users_show_assigned_codes_not_admin_wildcard(app, client, sdk, monkeypatch):
    app.app.dependency_overrides[current_user] = lambda: Principal(id=UID, is_super_admin=True, permissions=[])
    monkeypatch.setattr(DirectoryRepository,"users",lambda *a:SimpleNamespace(
        data=[{"id":UID,"email":"user@example.com","is_super_admin":True,"is_first_login":False}],count=21))
    monkeypatch.setattr(DirectoryRepository,"assigned_permissions",lambda *a:{UID:["USER_VIEW"]})
    response=client.get("/api/v1/users?page=2&page_size=20")
    assert response.status_code==200
    body=response.json()["data"]
    assert body["items"][0]["permissions"]==["USER_VIEW"]
    assert body["pagination"]=={"page":2,"page_size":20,"total":21,"total_pages":2,"has_next":False,"has_previous":True}
    assert response.headers["cache-control"]=="no-store"


def test_sdk_auth_query_and_batched_permissions(monkeypatch):
    import app.services.supabase as service
    original=httpx.Client
    seen=[]
    def handle(request):
        seen.append(request)
        if request.url.path=="/auth/v1/user":
            assert request.headers["authorization"]=="Bearer user-access"
            return httpx.Response(200,json={"id":UID,"email":"user@example.com","aud":"authenticated",
                "created_at":"2026-01-01T00:00:00Z","app_metadata":{},"user_metadata":{}})
        assert request.headers["authorization"]=="Bearer test-service-key"
        if request.url.path=="/rest/v1/profiles":
            if "id" in request.url.params:
                assert request.url.params["id"]=="eq."+UID
                return httpx.Response(200,json=[{"id":UID,"is_super_admin":True,"is_first_login":False}])
            assert request.url.params["offset"]=="0"
            assert request.url.params["limit"]=="20"
            assert request.url.params["order"]=="id.asc"
            assert "count=exact" in request.headers["prefer"]
            return httpx.Response(200,headers={"content-range":"0-0/1"},json=[
                {"id":UID,"email":"user@example.com","is_super_admin":False,"is_first_login":False}])
        if request.url.path=="/rest/v1/user_permissions":
            assert UID in request.url.params["user_id"]
            rows=[{"user_id":UID,"permission_id":1,"permissions":{"permission_code":"USER_VIEW"}}]
            return httpx.Response(200,json=rows if request.url.params["offset"]=="0" else [])
        raise AssertionError("Unexpected request")
    monkeypatch.setattr(service.httpx,"Client",lambda **kw:original(transport=httpx.MockTransport(handle),**kw))
    app=create_app(Settings(_env_file=None,supabase_url="https://example.supabase.co",
                            supabase_service_role_key="test-service-key",cors_origins=""))
    with TestClient(app) as client:
        response=client.get("/api/v1/users",headers={"Authorization":"Bearer user-access"})
    assert response.status_code==200
    assert response.json()["data"]["items"][0]["permissions"]==["USER_VIEW"]
    assert len(seen)==5

