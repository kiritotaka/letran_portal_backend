from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Response
from supabase import Client
from app.dependencies.auth import Principal, require_any_permission
from app.schemas.health import ErrorResponse
from app.schemas.user_management import CreateUserRequest, UpdateUserRequest, UserResponse
from app.services.supabase import get_supabase_client
from app.services.user_management import create_user, update_user, deactivate_user

router = APIRouter(prefix="/users",tags=["administration"],responses={
    code:{"model":ErrorResponse} for code in (401,403,404,409,422,429,503)
})


@router.post("",response_model=UserResponse,status_code=201)
def create_user_endpoint(
    payload: CreateUserRequest, response: Response,
    actor: Annotated[Principal,Depends(require_any_permission("USER_CREATE"))],
    client: Annotated[Client,Depends(get_supabase_client)],
):
    response.headers["Cache-Control"]="no-store"
    return create_user(payload,actor,client)


@router.patch("/{user_id}",response_model=UserResponse)
def update_user_endpoint(
    user_id: UUID, payload: UpdateUserRequest, response: Response,
    actor: Annotated[Principal,Depends(require_any_permission("USER_UPDATE"))],
    client: Annotated[Client,Depends(get_supabase_client)],
):
    response.headers["Cache-Control"]="no-store"
    return update_user(str(user_id),payload,actor,client)


@router.post("/{user_id}/deactivate",response_model=UserResponse)
def deactivate_user_endpoint(
    user_id: UUID, response: Response,
    actor: Annotated[Principal,Depends(require_any_permission("USER_REMOVE"))],
    client: Annotated[Client,Depends(get_supabase_client)],
):
    response.headers["Cache-Control"]="no-store"
    return deactivate_user(str(user_id),actor,client)
