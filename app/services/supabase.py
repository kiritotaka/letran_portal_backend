import logging
from collections.abc import Iterator

import httpx
from fastapi import Request
from supabase import Client, ClientOptions, create_client

from app.core.errors import ServiceUnavailable

logger = logging.getLogger(__name__)


def get_auth_client(request: Request) -> Iterator[Client]:
    # Sign-in mutates SDK authorization. Keep this separate from the service-role
    # data client so profile queries do not accidentally run under user RLS.
    yield from get_supabase_client(request)


def get_supabase_client(request: Request) -> Iterator[Client]:
    settings = request.app.state.settings
    key = settings.supabase_service_role_key.get_secret_value()
    if settings.supabase_url is None or not key.strip():
        raise ServiceUnavailable("SUPABASE_NOT_CONFIGURED", "Supabase is not configured.")
    # Request-scoped transport is closed deterministically; no shared Auth session.
    with httpx.Client(timeout=5.0) as transport:
        try:
            client = create_client(
                str(settings.supabase_url).rstrip("/"),
                key,
                options=ClientOptions(
                    auto_refresh_token=False,
                    persist_session=False,
                    postgrest_client_timeout=5,
                    httpx_client=transport,
                ),
            )
        except Exception as exc:
            logger.warning("Supabase initialization failed (%s)", type(exc).__name__)
            raise ServiceUnavailable("SUPABASE_UNAVAILABLE", "Supabase is unavailable.") from None
        yield client


def check_supabase(client: Client) -> None:
    try:
        # HEAD returns no profile rows. LIMIT avoids a full count/table scan.
        client.table("profiles").select("*", head=True).limit(1).execute()
    except Exception as exc:
        logger.warning("Supabase health check failed (%s)", type(exc).__name__)
        raise ServiceUnavailable("SUPABASE_UNAVAILABLE", "Supabase is unavailable.") from None
