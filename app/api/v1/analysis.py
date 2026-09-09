from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Header, Request
from app.api.v1.documents import Editor, Viewer, SDK, Page, no_cache, page_result
from fastapi import Depends
from app.core.errors import ApiError
from app.repositories.analysis import AnalysisRepository
from app.repositories.documents import DocumentRepository
from app.schemas.analysis import JobItem
from app.schemas.documents import DocumentResponse
from app.schemas.health import ErrorResponse
from app.schemas.lists import ListResponse

router=APIRouter(tags=['document-analysis'],dependencies=[Depends(no_cache)],
 responses={c:{'model':ErrorResponse} for c in (401,403,404,409,413,422,503)})


@router.post('/document-requests/{request_id}/jobs',status_code=202,response_model=DocumentResponse[JobItem])
def create_job(request_id: UUID, request: Request, actor: Editor, client: SDK,
 idempotency_key: Annotated[UUID,Header(alias='Idempotency-Key')]):
    settings=request.app.state.settings
    if not settings.analysis_worker_enabled or not settings.gemini_api_key.get_secret_value().strip():
        raise ApiError(503,'AI_NOT_CONFIGURED','Configure GEMINI_API_KEY and enable ANALYSIS_WORKER_ENABLED.')
    return {'data':AnalysisRepository(client).enqueue(actor,request_id,idempotency_key,settings.gemini_model)}


@router.get('/document-jobs/{job_id}',response_model=DocumentResponse[JobItem])
def get_job(job_id: UUID, actor: Viewer, client: SDK):
    return {'data':AnalysisRepository(client).get(job_id)}


@router.get('/document-requests/{request_id}/jobs',response_model=ListResponse[JobItem])
def list_jobs(request_id: UUID, actor: Viewer, client: SDK, params: Page):
    DocumentRepository(client).one('portal_document_requests',request_id)
    return page_result(AnalysisRepository(client).list(request_id,params),params)
