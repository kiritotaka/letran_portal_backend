from pydantic import Field, HttpUrl, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore",
        hide_input_in_errors=True,
    )

    supabase_url: HttpUrl | None = None
    supabase_service_role_key: SecretStr = SecretStr("")
    gemini_api_key: SecretStr = SecretStr("")
    gemini_model: str = Field(default="gemini-3.6-flash", pattern=r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,99}$")
    analysis_worker_enabled: bool = False
    cors_origins: str = "http://localhost:3000,http://localhost:5173"

    @field_validator("supabase_url", mode="before")
    @classmethod
    def empty_url(cls, value):
        return None if value == "" else value

    @field_validator("cors_origins")
    @classmethod
    def validate_origins(cls, value: str) -> str:
        from urllib.parse import urlsplit
        for origin in value.split(","):
            origin = origin.strip()
            if not origin:
                continue
            parsed = urlsplit(origin)
            if (
                parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.path or parsed.query or parsed.fragment
                or parsed.username or parsed.password
            ):
                raise ValueError("CORS_ORIGINS must contain comma-separated HTTP(S) origins without paths")
            try:
                parsed.port
            except ValueError:
                raise ValueError("Invalid origin port") from None
        return value

    @property
    def allowed_origins(self) -> list[str]:
        return list(dict.fromkeys(x.strip() for x in self.cors_origins.split(",") if x.strip()))
