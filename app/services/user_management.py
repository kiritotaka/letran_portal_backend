from supabase import Client
from supabase_auth.errors import AuthApiError
from app.core.errors import ApiError
from app.dependencies.auth import Principal
from app.repositories.user_management import UserManagementRepository
from app.schemas.user_management import CreateUserRequest, UpdateUserRequest, UserResponse


def auth_write(operation):
    try:
        return operation()
    except AuthApiError as exc:
        if exc.code in {"email_exists","email_already_exists","user_already_exists"}:
            raise ApiError(409,"EMAIL_ALREADY_EXISTS","Email already exists.") from None
        if exc.code in {"weak_password","validation_failed"}:
            raise ApiError(422,"INVALID_USER_DATA","Account data does not meet Supabase policy.") from None
        if exc.status == 429:
            raise ApiError(429,"AUTH_RATE_LIMITED","Too many account operations. Try later.") from None
        raise ApiError(503,"AUTH_WRITE_UNCONFIRMED","Auth write could not be confirmed. Check the account before retrying.") from None
    except Exception:
        raise ApiError(503,"AUTH_WRITE_UNCONFIRMED","Auth write could not be confirmed. Check the account before retrying.") from None


def create_user(payload: CreateUserRequest, actor: Principal, client: Client) -> UserResponse:
    repo = UserManagementRepository(client)
    values = {"email":str(payload.email),"permission_ids":payload.permission_ids,
              "is_super_admin":payload.is_super_admin,"is_active":True}
    # Fail before creating an Auth account if SQL is missing or authorization fails.
    repo.manage(str(actor.id),"create",validate_only=True,**values)
    result = auth_write(lambda: client.auth.admin.create_user({
        "email":str(payload.email),"password":payload.password.get_secret_value(),
        "email_confirm":True,"ban_duration":"876000h",
    }))
    if result.user is None:
        raise ApiError(503,"AUTH_WRITE_UNCONFIRMED","Account creation could not be confirmed.")
    user_id = str(result.user.id)
    try:
        data = repo.manage(str(actor.id),"create",user_id,**values)
    except ApiError:
        # Keep the newly created Auth user banned; do not delete after an ambiguous RPC.
        raise ApiError(503,"USER_PROVISIONING_INCOMPLETE",
                       "Auth account created but portal provisioning is incomplete. An administrator must reconcile the account; do not retry creation.") from None
    try:
        auth_write(lambda: client.auth.admin.update_user_by_id(user_id,{"ban_duration":"none"}))
    except ApiError:
        raise ApiError(503,"USER_AUTH_SYNC_INCOMPLETE","Portal account created but Auth activation is unconfirmed. Reload users and retry is_active=true.") from None
    return UserResponse(data=data)


def update_user(user_id: str, payload: UpdateUserRequest, actor: Principal, client: Client) -> UserResponse:
    repo = UserManagementRepository(client)
    values = payload.model_dump(exclude_unset=True)
    if "email" in values:
        values["email"] = str(values["email"])
    repo.manage(str(actor.id),"update",user_id,validate_only=True,**values)
    email_changed = False
    if "email" in values:
        # Supabase Auth owns login email. Profile follows only after Auth confirms.
        auth_write(lambda: client.auth.admin.update_user_by_id(user_id,{"email":values["email"],"email_confirm":True}))
        email_changed = True
    try:
        data = repo.manage(str(actor.id),"update",user_id,**values)
    except ApiError:
        if email_changed:
            raise ApiError(503,"USER_EMAIL_SYNC_INCOMPLETE","Auth email changed but portal update is unconfirmed. Reload and reconcile the account.") from None
        raise
    if "is_active" in values:
        sync_active(user_id,values["is_active"],client)
    return UserResponse(data=data)


def sync_active(user_id: str, active: bool, client: Client):
    try:
        auth_write(lambda: client.auth.admin.update_user_by_id(user_id,{"ban_duration":"none" if active else "876000h"}))
    except ApiError:
        raise ApiError(503,"USER_AUTH_SYNC_INCOMPLETE",
                       "Portal status saved but Supabase Auth status is unconfirmed. Reload and retry the status operation.") from None


def deactivate_user(user_id: str, actor: Principal, client: Client) -> UserResponse:
    data = UserManagementRepository(client).manage(str(actor.id),"deactivate",user_id)
    # Portal is blocked first, so even an Auth outage cannot allow backend access.
    sync_active(user_id,False,client)
    return UserResponse(data=data)
