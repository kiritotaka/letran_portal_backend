from typing import Annotated
from uuid import UUID

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel
from supabase import Client
from supabase_auth.errors import AuthApiError

from app.core.errors import ApiError, ServiceUnavailable
from app.repositories.users import UserRepository
from app.services.supabase import get_supabase_client

bearer = HTTPBearer(auto_error=False)


class Principal(BaseModel):
    id: UUID
    is_super_admin: bool
    permissions: list[str]


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    client: Annotated[Client, Depends(get_supabase_client)],
) -> Principal:
    if credentials is None:
        raise ApiError(401, "UNAUTHENTICATED", "A Bearer access token is required.")
    try:
        result = client.auth.get_user(credentials.credentials)
    except AuthApiError as exc:
        if exc.status in {400, 401, 403, 404, 422}:
            raise ApiError(401, "INVALID_ACCESS_TOKEN", "Access token is invalid or expired.") from None
        raise ServiceUnavailable("AUTH_UNAVAILABLE", "Authentication service is unavailable.") from None
    except Exception:
        raise ServiceUnavailable("AUTH_UNAVAILABLE", "Authentication service is unavailable.") from None
    if result.user is None:
        raise ApiError(401, "INVALID_ACCESS_TOKEN", "Access token is invalid or expired.")
    try:
        repository = UserRepository(client)
        profile = repository.get_profile(str(result.user.id))
        if profile is None:
            raise ApiError(403, "PROFILE_NOT_FOUND", "Portal profile is unavailable.")
        if profile["is_first_login"] is not False:
            raise ApiError(403, "PASSWORD_CHANGE_REQUIRED", "Change your initial password before accessing this API.")
        admin = profile["is_super_admin"] is True
        return Principal(id=result.user.id, is_super_admin=admin,
                         permissions=[] if admin else repository.get_permissions(str(result.user.id)))
    except ApiError:
        raise
    except Exception:
        raise ServiceUnavailable("PROFILE_UNAVAILABLE", "Account information is unavailable.") from None


def require_any_permission(*codes: str):
    def authorize(user: Annotated[Principal, Depends(current_user)]) -> Principal:
        if not user.is_super_admin and not set(codes).intersection(user.permissions):
            raise ApiError(403, "FORBIDDEN", "You do not have permission to access this resource.")
        return user
    return authorize

