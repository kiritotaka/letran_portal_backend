from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Header
from app.api.v1.files import SDK, no_cache
from app.dependencies.auth import Principal, require_any_permission
from app.repositories.product_imports import ProductImportRepository
from app.schemas.documents import DocumentResponse
from app.schemas.health import ErrorResponse
from app.schemas.lists import ListResponse
from app.schemas.product_imports import CreateProductImport, ProductImportJob, PreviewFilters, PreviewRow

router = APIRouter(prefix='/product-imports', tags=['product-imports'],
                   dependencies=[Depends(no_cache)],
                   responses={c: {'model': ErrorResponse} for c in (401, 403, 404, 409, 422, 429, 503)})
Actor = Annotated[Principal, Depends(require_any_permission('PRODUCT_IMPORT'))]


@router.post('', status_code=202, response_model=DocumentResponse[ProductImportJob])
def create_import(body: CreateProductImport, actor: Actor, client: SDK,
                  idempotency_key: Annotated[UUID, Header(alias='Idempotency-Key')]):
    return {'data': ProductImportRepository(client).action(actor, 'create', idempotency_key, body.model_dump(mode='json'))}


@router.get('/{job_id}', response_model=DocumentResponse[ProductImportJob])
def get_import(job_id: UUID, actor: Actor, client: SDK):
    return {'data': ProductImportRepository(client).action(actor, 'get', job_id)}


@router.get('/{job_id}/rows', response_model=ListResponse[PreviewRow])
def preview_rows(job_id: UUID, actor: Actor, client: SDK, filters: Annotated[PreviewFilters, Depends()]):
    return {'data': ProductImportRepository(client).action(actor, 'rows', job_id, filters.model_dump())}
