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
        import_stop = None
        if settings.analysis_worker_enabled and settings.gemini_api_key.get_secret_value() and settings.supabase_url:
            from app.services.analysis_worker import start_worker
            stop = start_worker(settings)
        if settings.product_import_worker_enabled and settings.supabase_url and settings.supabase_service_role_key.get_secret_value():
            from app.services.product_import_worker import start_worker as start_import_worker
            import_stop = start_import_worker(settings)
        try:
            yield
        finally:
            if stop is not None:
                stop.set()
            if import_stop is not None:
                import_stop.set()
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
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
    )


app = create_app()
