import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_environment(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-only-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "test-only-gemini")
    monkeypatch.setenv("CORS_ORIGINS", "https://portal.example, http://localhost:5173")
    settings = Settings(_env_file=None)
    assert settings.supabase_url.host == "example.supabase.co"
    assert settings.allowed_origins == ["https://portal.example", "http://localhost:5173"]
    assert settings.supabase_service_role_key.get_secret_value() == "test-only-secret"
    assert "test-only-secret" not in repr(settings)
    assert "test-only-gemini" not in repr(settings)


@pytest.mark.parametrize("origin", ["*", "invalid", "https://example.com/path", "https://example.com/"])
def test_reject_invalid_origins(origin):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, cors_origins=origin)


def test_empty_environment_file(tmp_path):
    env = tmp_path / ".env"
    env.write_text("SUPABASE_URL=\nSUPABASE_SERVICE_ROLE_KEY=\nGEMINI_API_KEY=\nCORS_ORIGINS=\n")
    settings = Settings(_env_file=env)
    assert settings.supabase_url is None
    assert settings.allowed_origins == []

