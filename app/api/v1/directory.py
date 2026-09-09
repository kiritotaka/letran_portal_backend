from typing import Annotated
from fastapi import APIRouter, Depends, Response
from supabase import Client

from app.dependencies.auth import require_any_permission
from app.repositories.directory import DirectoryRepository
from app.schemas.health import ErrorResponse
from app.schemas.lists import ListResponse, PaginationParams, PermissionItem, UserItem
from app.services.directory import list_permissions, list_users
from app.services.supabase import get_supabase_client

router = APIRouter(tags=["administration"], responses={
    code: {"model": ErrorResponse} for code in (401, 403, 422, 503)
})


@router.get("/permissions", response_model=ListResponse[PermissionItem],
            dependencies=[Depends(require_any_permission("PERM_VIEW", "USER_CREATE", "USER_UPDATE"))])
def permissions_endpoint(
    response: Response,
    params: Annotated[PaginationParams, Depends()],
    client: Annotated[Client, Depends(get_supabase_client)],
):
    response.headers["Cache-Control"] = "no-store"
    return list_permissions(params, DirectoryRepository(client))


@router.get("/users", response_model=ListResponse[UserItem],
            dependencies=[Depends(require_any_permission("USER_VIEW"))])
def users_endpoint(
    response: Response,
    params: Annotated[PaginationParams, Depends()],
    client: Annotated[Client, Depends(get_supabase_client)],
):
    response.headers["Cache-Control"] = "no-store"
    return list_users(params, DirectoryRepository(client))

