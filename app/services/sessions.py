from supabase import Client
from supabase_auth.errors import AuthApiError

from app.core.errors import ApiError
from app.repositories.users import UserRepository
from app.schemas.auth import LoginResponse, RefreshRequest
from app.services.auth import session_response


def refresh_session(payload: RefreshRequest, auth_client: Client, repository: UserRepository) -> LoginResponse:
    try:
        result = auth_client.auth.refresh_session(payload.refresh_token.get_secret_value())
    except AuthApiError as exc:
        if exc.status == 429:
            raise ApiError(429, "AUTH_RATE_LIMITED", "Too many refresh attempts. Try again later.") from None
        if exc.code in {
            "refresh_token_not_found", "refresh_token_already_used",
            "session_not_found", "session_expired", "user_not_found", "user_banned",
            "invalid_credentials",
        } or exc.status in {400, 401, 403, 422}:
            raise ApiError(401, "INVALID_REFRESH_TOKEN", "Session is invalid or expired. Sign in again.") from None
        raise refresh_unavailable() from None
    except Exception:
        raise refresh_unavailable() from None

    if result.session is None or result.user is None:
        raise refresh_unavailable()
    try:
        # Reload authorization from the database, not client input or stale metadata.
        return session_response(result, repository)
    except ApiError:
        raise
    except Exception:
        # Rotation may already have happened. Do not encourage replay of the old token.
        raise ApiError(
            503, "REFRESH_PROFILE_UNAVAILABLE",
            "Session refreshed, but account information is unavailable. Sign in again.",
        ) from None


def refresh_unavailable() -> ApiError:
    return ApiError(
        503, "REFRESH_UNAVAILABLE",
        "Session refresh could not be confirmed. Sign in again; do not automatically retry the old token.",
    )
