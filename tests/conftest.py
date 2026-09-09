import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def app():
    return create_app(Settings(
        _env_file=None, supabase_url=None, supabase_service_role_key="",
        gemini_api_key="", cors_origins="http://localhost:5173",
    ))


@pytest.fixture
def client(app):
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client

