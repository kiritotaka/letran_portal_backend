from datetime import datetime, timezone

from supabase import Client


class UserRepository:
    def __init__(self, client: Client):
        self.client = client

    def get_profile(self, user_id: str):
        result = self.client.table("profiles").select(
            "id,email,is_super_admin,is_first_login"
        ).eq("id", user_id).limit(1).execute()
        return result.data[0] if result.data else None

    def get_permissions(self, user_id: str) -> list[str]:
        codes = set()
        offset = 0
        while True:
            rows = self.client.table("user_permissions").select(
                "permission_id,permissions!user_permissions_permission_id_fkey(permission_code)"
            ).eq("user_id", user_id).order("permission_id").range(offset, offset + 499).execute().data
            for row in rows:
                permission = row.get("permissions")
                if permission and permission.get("permission_code"):
                    codes.add(permission["permission_code"])
            if not rows:
                break
            offset += len(rows)
        return sorted(codes)

    def complete_password_change(self, user_id: str) -> None:
        result = self.client.table("profiles").update({
            "is_first_login": False,
            "updated_by": user_id,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", user_id).execute()
        if (
            len(result.data) != 1
            or str(result.data[0]["id"]) != user_id
            or result.data[0]["is_first_login"] is not False
        ):
            raise RuntimeError("Profile update was not confirmed.")
