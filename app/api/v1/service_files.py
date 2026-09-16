from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, Query, Response, UploadFile
from supabase import Client

from app.core.errors import ApiError
from app.dependencies.auth import Principal, require_any_permission
from app.repositories.service_files import ServiceFileRepository
from app.schemas.health import ErrorResponse
from app.schemas.lists import ListResponse, PaginationParams
from app.schemas.service_files import (CreateServiceRequest, DownloadData, ServiceFileItem,
    ServiceFileResponse, ServiceRequestItem, UpdateServiceRequest)
from app.services.directory import pagination
from app.services.service_files import download_url, upload_file
from app.services.supabase import get_supabase_client


def no_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"


router = APIRouter(tags=["service-files"], dependencies=[Depends(no_cache)],
    responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 413, 415, 422, 503)})
# Admin bypasses via Principal.is_super_admin inside require_any_permission.
MechanicalUser = Annotated[Principal, Depends(require_any_permission(
    "MECHANICAL_CREATE", "MECHANICAL_UPDATE", "MECHANICAL_REMOVE", "MECHANICAL_VIEW"))]
SDK = Annotated[Client, Depends(get_supabase_client)]
Page = Annotated[PaginationParams, Query()]


def page_result(result, params):
    if result.count is None:
        raise ApiError(503, "SERVICE_FILES_UNAVAILABLE", "List total is unavailable.")
    return {"success": True, "data": {"items": result.data, "pagination": pagination(params, result.count)}}


@router.post("/service-requests", status_code=201, response_model=ServiceFileResponse[ServiceRequestItem])
def create_request(payload: CreateServiceRequest, actor: MechanicalUser, client: SDK):
    return {"data": ServiceFileRepository(client).write(actor, "create_request", **payload.model_dump(mode="json"))}


@router.get("/service-requests", response_model=ListResponse[ServiceRequestItem])
def requests(actor: MechanicalUser, client: SDK, params: Page):
    repo = ServiceFileRepository(client)
    return page_result(repo.page("portal_service_requests", params, order="created_at", desc=True), params)


@router.get("/service-requests/{request_id}", response_model=ServiceFileResponse[ServiceRequestItem])
def request_detail(request_id: UUID, actor: MechanicalUser, client: SDK):
    return {"data": ServiceFileRepository(client).one("portal_service_requests", request_id)}


@router.patch("/service-requests/{request_id}", response_model=ServiceFileResponse[ServiceRequestItem])
def update_request(request_id: UUID, payload: UpdateServiceRequest, actor: MechanicalUser, client: SDK):
    return {"data": ServiceFileRepository(client).write(actor, "update_request", request_id=str(request_id),
        **payload.model_dump(mode="json", exclude_unset=True))}


@router.post("/service-requests/{request_id}/files", status_code=201, response_model=ServiceFileResponse[ServiceFileItem])
def upload(request_id: UUID, actor: MechanicalUser, client: SDK,
           idempotency_key: Annotated[UUID, Header(alias="Idempotency-Key")],
           file: Annotated[UploadFile, File()]):
    try:
        return {"data": upload_file(client, actor, request_id, idempotency_key, file)}
    finally:
        file.file.close()


@router.get("/service-requests/{request_id}/files", response_model=ListResponse[ServiceFileItem])
def files(request_id: UUID, actor: MechanicalUser, client: SDK, params: Page):
    repo = ServiceFileRepository(client)
    repo.one("portal_service_requests", request_id)
    return page_result(repo.page("portal_service_files", params, {"request_id": request_id}, order="created_at"), params)


@router.post("/service-requests/{request_id}/files/{file_id}/delete", response_model=ServiceFileResponse[ServiceFileItem])
def delete_file(request_id: UUID, file_id: UUID, actor: MechanicalUser, client: SDK):
    return {"data": ServiceFileRepository(client).write(actor, "delete_file",
        request_id=str(request_id), file_id=str(file_id))}


@router.get("/service-requests/{request_id}/files/{file_id}/download-url", response_model=ServiceFileResponse[DownloadData])
def download(request_id: UUID, file_id: UUID, actor: MechanicalUser, client: SDK):
    return {"data": download_url(client, request_id, file_id)}
