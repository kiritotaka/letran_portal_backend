from typing import Annotated

from fastapi import APIRouter, Depends, Response
from supabase import Client

from app.repositories.users import UserRepository
from app.schemas.auth import ChangePasswordRequest, ChangePasswordResponse, LoginRequest, LoginResponse
from app.schemas.health import ErrorResponse
from app.services.auth import login
from app.services.passwords import change_password
from app.services.supabase import get_auth_client, get_supabase_client

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse, responses={
    code: {"model": ErrorResponse} for code in (401, 403, 422, 429, 503)
})
def login_endpoint(
    payload: LoginRequest,
    response: Response,
    auth_client: Annotated[Client, Depends(get_auth_client)],
    data_client: Annotated[Client, Depends(get_supabase_client)],
) -> LoginResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return login(payload, auth_client, UserRepository(data_client))


PASSWORD_ERRORS = {code: {"model": ErrorResponse} for code in (401, 403, 409, 422, 429, 503)}


@router.post("/change-password", response_model=ChangePasswordResponse, responses=PASSWORD_ERRORS)
def change_password_endpoint(
    payload: ChangePasswordRequest,
    response: Response,
    auth_client: Annotated[Client, Depends(get_auth_client)],
    data_client: Annotated[Client, Depends(get_supabase_client)],
) -> ChangePasswordResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return change_password(payload, auth_client, UserRepository(data_client))


@router.post("/change-password-first-login", response_model=ChangePasswordResponse, responses=PASSWORD_ERRORS)
def change_first_password_endpoint(
    payload: ChangePasswordRequest,
    response: Response,
    auth_client: Annotated[Client, Depends(get_auth_client)],
    data_client: Annotated[Client, Depends(get_supabase_client)],
) -> ChangePasswordResponse:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return change_password(payload, auth_client, UserRepository(data_client), first_login_only=True)
