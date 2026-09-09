import logging

from supabase import Client
from supabase_auth.errors import AuthApiError

from app.core.errors import ApiError, ServiceUnavailable
from app.repositories.users import UserRepository
from app.schemas.auth import ChangePasswordRequest, ChangePasswordResponse
from app.services.auth import authenticate_password

logger = logging.getLogger(__name__)


def change_password(
    payload: ChangePasswordRequest,
    auth_client: Client,
    repository: UserRepository,
    *,
    first_login_only: bool = False,
) -> ChangePasswordResponse:
    result = authenticate_password(
        str(payload.email), payload.current_password.get_secret_value(), auth_client,
    )
    # Identity comes exclusively from Supabase's password authentication response.
    user_id = str(result.user.id)
    try:
        try:
            profile = repository.get_profile(user_id)
        except Exception:
            raise ServiceUnavailable("PROFILE_UNAVAILABLE", "Account information is unavailable.") from None
        if profile is None:
            raise ApiError(403, "PROFILE_NOT_FOUND", "Account has no portal profile. Contact an administrator.")
        if first_login_only and profile["is_first_login"] is False:
            raise ApiError(409, "FIRST_LOGIN_ALREADY_COMPLETED", "Use the regular change-password endpoint.")

        try:
            updated = auth_client.auth.update_user({"password": payload.new_password.get_secret_value()})
            if updated.user is None or str(updated.user.id) != user_id:
                raise RuntimeError("Password update was not confirmed.")
        except AuthApiError as exc:
            if exc.status == 429:
                raise ApiError(429, "AUTH_RATE_LIMITED", "Too many attempts. Try again later.") from None
            if exc.code in {"weak_password", "same_password", "validation_failed"}:
                raise ApiError(422, "PASSWORD_POLICY_VIOLATION", "New password does not meet the password policy.") from None
            if exc.code in {"reauthentication_needed", "reauthentication_not_valid", "insufficient_aal"}:
                raise ApiError(403, "REAUTHENTICATION_REQUIRED", "Additional Supabase authentication is required.") from None
            if exc.status == 401:
                raise ApiError(401, "INVALID_SESSION", "Authentication expired. Sign in again.") from None
            # A failed/ambiguous write must not be treated as definitely unchanged.
            raise password_status_unknown() from None
        except Exception:
            raise password_status_unknown() from None

        try:
            repository.complete_password_change(user_id)
        except Exception:
            # Auth and public.profiles cannot be updated in one transaction.
            # Never roll back a password, clear the flag early, or return false success.
            raise ApiError(
                503, "PASSWORD_CHANGED_PROFILE_SYNC_FAILED",
                "Password changed, but profile update could not be confirmed. "
                "Sign in with the new password and contact an administrator if first-login remains required.",
            ) from None
        return ChangePasswordResponse()
    finally:
        # Revoke only the temporary session created by reauthentication.
        # Other sessions/access JWTs follow Supabase's configured lifecycle.
        try:
            auth_client.auth.sign_out({"scope": "local"})
        except Exception as exc:
            logger.warning("Temporary auth session cleanup failed (%s)", type(exc).__name__)


def password_status_unknown() -> ApiError:
    return ApiError(
        503, "PASSWORD_CHANGE_STATUS_UNKNOWN",
        "Password update could not be confirmed. Try signing in with the new password "
        "before retrying; the first-login flag has not been updated.",
    )
