from supabase import Client
from supabase_auth.errors import AuthApiError

from app.core.errors import ApiError, ServiceUnavailable
from app.repositories.users import UserRepository
from app.schemas.auth import LoginData, LoginRequest, LoginResponse, LoginUser


def authenticate_password(email: str, password: str, auth_client: Client):
    try:
        result = auth_client.auth.sign_in_with_password({
            "email": email,
            "password": password,
        })
    except AuthApiError as exc:
        if exc.status == 429:
            raise ApiError(429, "AUTH_RATE_LIMITED", "Too many login attempts. Try again later.") from None
        if exc.code in {"invalid_credentials", "email_not_confirmed", "user_banned"}:
            raise ApiError(401, "INVALID_CREDENTIALS", "Email or password is incorrect, or account is unavailable.") from None
        raise ServiceUnavailable("AUTH_UNAVAILABLE", "Authentication service is unavailable.") from None
    except Exception:
        raise ServiceUnavailable("AUTH_UNAVAILABLE", "Authentication service is unavailable.") from None

    if result.session is None or result.user is None:
        raise ServiceUnavailable("AUTH_UNAVAILABLE", "Authentication service is unavailable.")
    return result


def login(payload: LoginRequest, auth_client: Client, repository: UserRepository) -> LoginResponse:
    result = authenticate_password(str(payload.email), payload.password.get_secret_value(), auth_client)
    return session_response(result, repository)


def session_response(result, repository: UserRepository) -> LoginResponse:
    try:
        profile = repository.get_profile(str(result.user.id))
        if profile is None:
            raise ApiError(403, "PROFILE_NOT_FOUND", "Account has no portal profile. Contact an administrator.")
        if profile.get("isActive") is not True:
            raise ApiError(403, "ACCOUNT_INACTIVE", "Account is inactive. Contact an administrator.")
        is_admin = profile["is_super_admin"] is True
        permissions = ["*"] if is_admin else repository.get_permissions(str(result.user.id))
        user = LoginUser(
            id=result.user.id, email=result.user.email,
            is_super_admin=is_admin, is_active=True,
            is_first_login=profile["is_first_login"] is not False,
            permissions=permissions,
        )
        return LoginResponse(data=LoginData(
            access_token=result.session.access_token,
            refresh_token=result.session.refresh_token,
            expires_in=result.session.expires_in,
            expires_at=result.session.expires_at,
            user=user,
        ))
    except ApiError:
        raise
    except Exception:
        raise ServiceUnavailable("PROFILE_UNAVAILABLE", "Account information is unavailable.") from None
