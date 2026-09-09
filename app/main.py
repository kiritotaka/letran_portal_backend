from fastapi import FastAPI
from contextlib import asynccontextmanager
from starlette.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import Settings
from app.core.errors import register_error_handlers
from app.core.upload_limit import UploadBodyLimit


def create_app(settings: Settings | None = None) -> CORSMiddleware:
    settings = settings if settings is not None else Settings()
    @asynccontextmanager
    async def lifespan(api):
        stop = None
        if settings.analysis_worker_enabled and settings.gemini_api_key.get_secret_value() and settings.supabase_url:
            from app.services.analysis_worker import start_worker
            stop = start_worker(settings)
        try:
            yield
        finally:
            if stop is not None:
                stop.set()
    api = FastAPI(title="Letran Portal Backend", version="0.1.0", lifespan=lifespan)
    api.state.settings = settings
    register_error_handlers(api)
    api.add_middleware(UploadBodyLimit)
    api.include_router(api_router)
    # Outer CORS middleware also covers unhandled 500 responses.
    return CORSMiddleware(
        app=api,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "PUT"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )


app = create_app()
