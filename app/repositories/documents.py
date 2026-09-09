from postgrest.exceptions import APIError

from app.core.errors import ApiError


def execute(query):
    try:
        return query.execute()
    except APIError as exc:
        codes = {"FORBIDDEN": 403, "CATALOG_NOT_FOUND": 404, "REQUEST_NOT_FOUND": 404,
                 "DOCUMENT_NOT_FOUND": 404, "FILE_NOT_FOUND": 404,
                 "REQUEST_ARCHIVED": 409, "IDEMPOTENCY_CONFLICT": 409, "FILE_DELETED": 409,
                 "FILE_LIMIT": 409, "DOCUMENT_LIMIT": 409, "INVALID_INPUT": 422}
        if exc.message in codes:
            raise ApiError(codes[exc.message], exc.message, exc.message.replace("_", " ").capitalize()+".") from None
        if exc.code in {"PGRST202", "PGRST205", "42P01"}:
            raise ApiError(503, "DOCUMENTS_NOT_INSTALLED", "Install migration 002_portal_documents.sql first.") from None
        raise ApiError(503, "DOCUMENT_WRITE_UNCONFIRMED", "Document operation is unconfirmed. Reload before retrying.") from None
    except Exception:
        raise ApiError(503, "DOCUMENTS_UNAVAILABLE", "Document service is unavailable.") from None


class DocumentRepository:
    def __init__(self, client):
        self.client = client

    def write(self, actor, action, **data):
        return execute(self.client.rpc("portal_documents_write", {
            "p_actor_id": str(actor.id), "p_action": action, "p_data": data,
        })).data

    def requests(self, params):
        if not params.search and params.document_type_id is None:
            return self.page("portal_document_requests", params, order="created_at", desc=True)
        query = self.client.rpc("portal_search_document_requests", {
            "p_document_type_id": str(params.document_type_id) if params.document_type_id else None,
            "p_search": params.search,
        }, count="exact")
        try:
            return query.order("created_at", desc=True).order("id").range(
                params.offset, params.offset + params.page_size - 1).execute()
        except APIError as exc:
            if exc.code == "PGRST202":
                raise ApiError(503, "DOCUMENT_SEARCH_NOT_INSTALLED", "Install migration 003_document_search.sql first.") from None
            raise ApiError(503, "DOCUMENTS_UNAVAILABLE", "Document search is unavailable.") from None
        except Exception:
            raise ApiError(503, "DOCUMENTS_UNAVAILABLE", "Document search is unavailable.") from None

    def one(self, table, id):
        rows = execute(self.client.table(table).select("*").eq("id", str(id)).limit(1)).data
        if not rows:
            raise ApiError(404, "DOCUMENT_RESOURCE_NOT_FOUND", "Document resource was not found.")
        return rows[0]

    def page(self, table, params, filters=None, select="*", order="id", desc=False):
        query = self.client.table(table).select(select, count="exact")
        if table == "portal_document_request_files":
            query = query.neq("file.status", "deleted")
        for key, value in (filters or {}).items():
            query = query.eq(key, str(value) if not isinstance(value, bool) else value)
        query = query.order(order, desc=desc)
        if order != "id":
            query = query.order("file_id" if table == "portal_document_request_files" else "id")
        return execute(query.range(params.offset, params.offset+params.page_size-1))

    def file_for_request(self, request_id, file_id):
        rows = execute(self.client.table("portal_document_request_files")
            .select("file:portal_files!inner(*)").eq("request_id", str(request_id))
            .eq("file_id", str(file_id)).limit(1)).data
        if not rows:
            raise ApiError(404, "FILE_NOT_FOUND", "File was not found in this request.")
        return rows[0]["file"]
