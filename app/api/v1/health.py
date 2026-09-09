from typing import Annotated

from fastapi import APIRouter, Depends
from supabase import Client

from app.schemas.health import ErrorResponse, HealthResponse
from app.services.supabase import check_supabase, get_supabase_client

router = APIRouter(prefix="/health", tags=["health"])


@router.get("", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(service="letran-portal-backend")


@router.get("/supabase", response_model=HealthResponse, responses={503: {"model": ErrorResponse}})
def supabase_health(client: Annotated[Client, Depends(get_supabase_client)]) -> HealthResponse:
    check_supabase(client)
    return HealthResponse(service="supabase")

