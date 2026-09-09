from postgrest.exceptions import APIError
from supabase import Client
from app.core.errors import ApiError


class UserManagementRepository:
    def __init__(self, client: Client):
        self.client = client

    def manage(self, actor_id: str, action: str, user_id=None, *, validate_only=False, **values):
        payload = {"p_actor_id":actor_id,"p_action":action,"p_user_id":user_id,
                   "p_validate_only":validate_only}
        payload.update({"p_"+key:value for key,value in values.items()})
        try:
            return self.client.rpc("portal_manage_user", payload).execute().data
        except APIError as exc:
            message = str(exc.message)
            mapping = {
                "FORBIDDEN":403, "SELF_UPDATE_FORBIDDEN":403, "USER_NOT_FOUND":404,
                "INVALID_PERMISSION_IDS":422, "LAST_ADMIN_REQUIRED":409, "EMAIL_ALREADY_EXISTS":409,
            }
            if message in mapping:
                raise ApiError(mapping[message], message, message.replace("_"," ").capitalize()+".") from None
            if exc.code == "PGRST202":
                raise ApiError(503,"USER_MANAGEMENT_NOT_INSTALLED","Install the user-management SQL function first.") from None
            raise ApiError(503,"USER_WRITE_UNCONFIRMED","Database write could not be confirmed. Reload the user before retrying.") from None
        except Exception:
            raise ApiError(503,"USER_WRITE_UNCONFIRMED","Database write could not be confirmed. Reload the user before retrying.") from None
