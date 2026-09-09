from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import Settings
from app.core.errors import register_error_handlers


def create_app(settings: Settings | None = None) -> CORSMiddleware:
    settings = settings if settings is not None else Settings()
    api = FastAPI(title="Letran Portal Backend", version="0.1.0")
    api.state.settings = settings
    register_error_handlers(api)
    api.include_router(api_router)
    # Outer CORS middleware also covers unhandled 500 responses.
    return CORSMiddleware(
        app=api,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET"],
        allow_headers=["Authorization", "Content-Type"],
    )


app = create_app()

