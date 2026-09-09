from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Header, Query, Response, UploadFile
from supabase import Client

from app.core.errors import ApiError
from app.dependencies.auth import Principal, require_any_permission
from app.repositories.documents import DocumentRepository
from app.schemas.documents import (CatalogItem, CreateDocument, CreateRequest, DocumentItem,
    DocumentResponse, DownloadData, FileItem, FileOrder, LinkedFile, ReorderFile,
    RequestItem, TemplateItem, TemplateUrlData, UpdateRequest, RequestFilters, FileFilters)
from app.schemas.health import ErrorResponse
from app.schemas.lists import ListResponse, PaginationParams
from app.services.directory import pagination
from app.services.document_uploads import download_url, upload_file
from app.services.supabase import get_supabase_client


def no_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(tags=["documents"], dependencies=[Depends(no_cache)],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 415, 422, 503)})
Viewer = Annotated[Principal, Depends(require_any_permission("DOC_VIEW"))]
Creator = Annotated[Principal, Depends(require_any_permission("DOC_CREATE"))]
Editor = Annotated[Principal, Depends(require_any_permission("DOC_UPDATE"))]
Remover = Annotated[Principal, Depends(require_any_permission("DOC_REMOVE"))]
CatalogReader = Annotated[Principal, Depends(require_any_permission("DOC_VIEW", "DOC_CREATE", "DOC_UPDATE"))]
SDK = Annotated[Client, Depends(get_supabase_client)]
Page = Annotated[PaginationParams, Query()]


def page_result(result, params):
    if result.count is None:
        raise ApiError(503, "DOCUMENTS_UNAVAILABLE", "List total is unavailable.")
    return {"success": True, "data": {"items": result.data, "pagination": pagination(params, result.count)}}


@router.get("/document-tasks", response_model=ListResponse[CatalogItem])
def tasks(actor: CatalogReader, client: SDK, params: Page):
    return page_result(DocumentRepository(client).page("portal_document_tasks", params, {"is_active": True}), params)


@router.get("/document-types", response_model=ListResponse[CatalogItem])
def types(actor: CatalogReader, client: SDK, params: Page):
    return page_result(DocumentRepository(client).page("portal_document_types", params, {"is_active": True}), params)


@router.get("/document-tasks/{task_id}/templates", response_model=ListResponse[TemplateItem])
def templates(task_id: UUID, actor: CatalogReader, client: SDK, params: Page):
    repo = DocumentRepository(client)
    repo.one("portal_document_tasks", task_id)
    return page_result(repo.page("portal_document_templates", params, {"task_id": task_id}), params)


@router.post("/document-requests", status_code=201, response_model=DocumentResponse[RequestItem])
def create_request(payload: CreateRequest, actor: Creator, client: SDK):
    return {"data": DocumentRepository(client).write(actor, "create_request", **payload.model_dump(mode="json"))}


@router.get("/document-requests", response_model=ListResponse[RequestItem])
def requests(actor: Viewer, client: SDK, params: Annotated[RequestFilters, Query()]):
    return page_result(DocumentRepository(client).requests(params), params)


@router.get("/document-requests/{request_id}", response_model=DocumentResponse[RequestItem])
def request_detail(request_id: UUID, actor: Viewer, client: SDK):
    return {"data": DocumentRepository(client).one("portal_document_requests", request_id)}


@router.patch("/document-requests/{request_id}", response_model=DocumentResponse[RequestItem])
def update_request(request_id: UUID, payload: UpdateRequest, actor: Editor, client: SDK):
    return {"data": DocumentRepository(client).write(actor, "update_request", request_id=str(request_id),
        **payload.model_dump(mode="json", exclude_unset=True))}


@router.post("/document-requests/{request_id}/documents", status_code=201, response_model=DocumentResponse[DocumentItem])
def create_document(request_id: UUID, payload: CreateDocument, actor: Creator, client: SDK):
    return {"data": DocumentRepository(client).write(actor, "create_document", request_id=str(request_id),
        **payload.model_dump(mode="json"))}


@router.get("/document-requests/{request_id}/documents", response_model=ListResponse[DocumentItem])
def documents(request_id: UUID, actor: Viewer, client: SDK, params: Page):
    repo = DocumentRepository(client)
    repo.one("portal_document_requests", request_id)
    return page_result(repo.page("portal_documents", params, {"request_id": request_id}, order="created_at"), params)


@router.post("/document-requests/{request_id}/documents/{document_id}/files", response_model=DocumentResponse[FileItem])
def upload(request_id: UUID, document_id: UUID, actor: Creator, client: SDK,
           idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
           file: Annotated[UploadFile, File()], sort_order: Annotated[int, Form(ge=1, le=10000)] = 1):
    try:
        return {"data": upload_file(client, actor, request_id, document_id, idempotency_key, sort_order, file)}
    finally:
        file.file.close()


@router.get("/document-requests/{request_id}/files", response_model=ListResponse[LinkedFile])
def files(request_id: UUID, actor: Viewer, client: SDK, params: Annotated[FileFilters, Query()]):
    document_id = params.document_id
    repo = DocumentRepository(client)
    repo.one("portal_document_requests", request_id)
    filters = {"request_id": request_id}
    if document_id is not None:
        doc = repo.one("portal_documents", document_id)
        if str(doc["request_id"]) != str(request_id):
            raise ApiError(404, "DOCUMENT_NOT_FOUND", "Document is not in this request.")
        filters["document_id"] = document_id
    return page_result(repo.page("portal_document_request_files", params, filters,
        select="request_id,document_id,file_id,sort_order,file:portal_files!inner(*)", order="sort_order"), params)


@router.patch("/document-requests/{request_id}/files/{file_id}", response_model=DocumentResponse[FileOrder])
def reorder_file(request_id: UUID, file_id: UUID, payload: ReorderFile, actor: Editor, client: SDK):
    return {"data": DocumentRepository(client).write(actor, "reorder_file", request_id=str(request_id),
        file_id=str(file_id), sort_order=payload.sort_order)}


@router.post("/document-requests/{request_id}/files/{file_id}/delete", response_model=DocumentResponse[FileItem])
def delete_file(request_id: UUID, file_id: UUID, actor: Remover, client: SDK):
    # Soft deletion retains a tombstone and blocks signing immediately. It cannot
    # race a retry into resurrecting a visible file or destroy an ambiguous upload.
    return {"data": DocumentRepository(client).write(actor, "delete_file", request_id=str(request_id), file_id=str(file_id))}


@router.get("/document-requests/{request_id}/files/{file_id}/download-url", response_model=DocumentResponse[DownloadData])
def download(request_id: UUID, file_id: UUID, actor: Viewer, client: SDK):
    return {"data": download_url(client, request_id, file_id)}


@router.get("/document-requests/{request_id}/template-url", response_model=DocumentResponse[TemplateUrlData])
def request_template_url(request_id: UUID, actor: Viewer, client: SDK):
    repo = DocumentRepository(client)
    request = repo.one("portal_document_requests", request_id)
    if not request.get("template_id"):
        raise ApiError(404, "TEMPLATE_NOT_ASSIGNED", "This request has no template.")
    template = repo.one("portal_document_templates", request["template_id"])
    path = template.get("object_path")
    if not path:
        raise ApiError(409, "TEMPLATE_FILE_NOT_READY", "Template file has not been uploaded.")
    if template.get("bucket") != "portal_documents" or not path.startswith("templates/"):
        raise ApiError(503, "TEMPLATE_STORAGE_INVALID", "Template storage configuration is invalid.")
    try:
        signed = client.storage.from_("portal_documents").create_signed_url(path, 300)
        url = signed["signedURL"]
        if not isinstance(url, str) or not url.startswith("https://"):
            raise ValueError()
    except Exception:
        raise ApiError(503, "STORAGE_UNAVAILABLE", "Template URL is unavailable.") from None
    return {"data": {"template_id": str(template["id"]), "name": template["name"],
        "version": template["version"], "output_format": template["output_format"],
        "url": url, "expires_in": 300}}
