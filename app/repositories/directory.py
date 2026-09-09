from supabase import Client
from app.schemas.lists import PaginationParams


class DirectoryRepository:
    def __init__(self, client: Client):
        self.client = client

    def permissions(self, params: PaginationParams):
        return self.client.table("permissions").select(
            "id,permission_code,permission_name,group_id,"
            "group:permission_groups!permissions_group_id_fkey(id,group_name,description)",
            count="exact",
        ).order("id").range(params.offset, params.offset + params.page_size - 1).execute()

    def users(self, params: PaginationParams):
        return self.client.table("profiles").select(
            "id,email,is_super_admin,is_first_login,created_at,updated_at", count="exact",
        ).order("id").range(params.offset, params.offset + params.page_size - 1).execute()

    def assigned_permissions(self, user_ids: list[str]) -> dict[str, list[str]]:
        codes = {uid: set() for uid in user_ids}
        if not user_ids:
            return {}
        offset = 0
        while True:
            rows = self.client.table("user_permissions").select(
                "user_id,permission_id,permissions!user_permissions_permission_id_fkey(permission_code)"
            ).in_("user_id", user_ids).order("user_id").order("permission_id").range(offset, offset + 499).execute().data
            if not rows:
                break
            for row in rows:
                permission = row.get("permissions")
                if permission and permission.get("permission_code"):
                    codes[str(row["user_id"])].add(permission["permission_code"])
            offset += len(rows)
        return {uid: sorted(values) for uid, values in codes.items()}

