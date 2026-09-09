from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, Header, Query
from app.api.v1.documents import Editor, Viewer, SDK, no_cache
from app.repositories.documents import DocumentRepository
from app.repositories.document_review import ReviewRepository
from app.schemas.document_review import SaveReview, ReviewData, ExportInput, ExportData
from app.schemas.documents import DocumentResponse
from app.schemas.health import ErrorResponse
from app.services.document_export import create_export, export_url
from app.core.errors import ApiError

router=APIRouter(tags=['document-review'],dependencies=[Depends(no_cache)],
 responses={c:{'model':ErrorResponse} for c in (401,403,404,409,422,503)})


@router.put('/document-requests/{request_id}/review',response_model=DocumentResponse[ReviewData])
def save_review(request_id: UUID,payload: SaveReview,actor: Editor,client: SDK,
                idempotency_key: Annotated[UUID,Header(alias='Idempotency-Key')]):
    return {'data':ReviewRepository(client).save(actor,request_id,idempotency_key,payload)}


@router.get('/document-requests/{request_id}/review',response_model=DocumentResponse[ReviewData])
def get_review(request_id: UUID,actor: Viewer,client: SDK,revision: Annotated[int | None,Query(ge=1)]=None):
    DocumentRepository(client).one('portal_document_requests',request_id)
    return {'data':ReviewRepository(client).get(request_id,revision)}


@router.post('/document-requests/{request_id}/exports',response_model=DocumentResponse[ExportData])
def export_review(request_id: UUID,payload: ExportInput,actor: Editor,client: SDK):
    return {'data':create_export(client,actor,request_id,payload.revision)}


@router.get('/document-requests/{request_id}/exports/{revision}/download-url',response_model=DocumentResponse[ExportData])
def get_export_url(request_id: UUID,revision: int,actor: Viewer,client: SDK):
    DocumentRepository(client).one('portal_document_requests',request_id)
    repo=ReviewRepository(client); review=repo.get(request_id,revision)
    exported=repo.exported(review['id'])
    if not exported: raise ApiError(404,'EXPORT_NOT_FOUND','No export exists for this revision.')
    return {'data':export_url(client,review,exported)}
