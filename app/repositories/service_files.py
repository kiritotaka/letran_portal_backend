from postgrest.exceptions import APIError

from app.core.errors import ApiError


def execute(query):
    try:
        return query.execute()
    except APIError as exc:
        codes = {"FORBIDDEN": 403, "REQUEST_NOT_FOUND": 404, "FILE_NOT_FOUND": 404,
                 "REQUEST_ARCHIVED": 409, "IDEMPOTENCY_CONFLICT": 409, "FILE_DELETED": 409,
                 "FILE_LIMIT": 409, "INVALID_INPUT": 422}
        if exc.message in codes:
            raise ApiError(codes[exc.message], exc.message, exc.message.replace("_", " ").capitalize()+".") from None
        if exc.code in {"PGRST202", "PGRST205", "42P01"}:
            raise ApiError(503, "SERVICE_FILES_NOT_INSTALLED", "Install migration 007_service_files.sql first.") from None
        raise ApiError(503, "SERVICE_FILE_WRITE_UNCONFIRMED", "Service file operation is unconfirmed. Reload before retrying.") from None
    except Exception:
        raise ApiError(503, "SERVICE_FILES_UNAVAILABLE", "Service file storage is unavailable.") from None


class ServiceFileRepository:
    def __init__(self, client):
        self.client = client

    def write(self, actor, action, **data):
        return execute(self.client.rpc("portal_service_files_write", {
            "p_actor_id": str(actor.id), "p_action": action, "p_data": data,
        })).data

    def one(self, table, id):
        rows = execute(self.client.table(table).select("*").eq("id", str(id)).limit(1)).data
        if not rows:
            raise ApiError(404, "SERVICE_RESOURCE_NOT_FOUND", "Service resource was not found.")
        return rows[0]

    def page(self, table, params, filters=None, order="id", desc=False):
        query = self.client.table(table).select("*", count="exact")
        for key, value in (filters or {}).items():
            query = query.eq(key, str(value) if not isinstance(value, bool) else value)
        query = query.order(order, desc=desc)
        if order != "id":
            query = query.order("id")
        return execute(query.range(params.offset, params.offset + params.page_size - 1))
