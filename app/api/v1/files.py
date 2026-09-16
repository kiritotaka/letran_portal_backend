from typing import Annotated
from uuid import UUID
from fastapi import APIRouter, Depends, File, Form, Header, Response, UploadFile
from supabase import Client
from app.dependencies.auth import Principal, current_user
from app.services.supabase import get_supabase_client
from app.services.files import upload_file, download_url
from app.repositories.files import FileRepository
from app.schemas.files import UploadedFile, FileDownload
from app.schemas.documents import DocumentResponse
from app.schemas.health import ErrorResponse


def no_cache(response: Response): response.headers['Cache-Control']='no-store'

router=APIRouter(prefix='/files',tags=['files'],dependencies=[Depends(no_cache)],
 responses={c:{'model':ErrorResponse} for c in (401,403,404,409,413,415,422,503)})
Actor=Annotated[Principal,Depends(current_user)]
SDK=Annotated[Client,Depends(get_supabase_client)]


@router.post('',response_model=DocumentResponse[UploadedFile])
def upload(actor:Actor,client:SDK,purpose:Annotated[str,Form()],file:Annotated[UploadFile,File()],
           idempotency_key:Annotated[UUID,Header(alias='Idempotency-Key')]):
    try: return {'data':upload_file(client,actor,idempotency_key,purpose,file)}
    finally: file.file.close()


@router.get('/{file_id}',response_model=DocumentResponse[UploadedFile])
def metadata(file_id:UUID,actor:Actor,client:SDK):
    return {'data':FileRepository(client).action(actor,'get',file_id)}


@router.get('/{file_id}/download-url',response_model=DocumentResponse[FileDownload])
def download(file_id:UUID,actor:Actor,client:SDK):
    return {'data':download_url(client,actor,file_id)}


@router.delete('/{file_id}',response_model=DocumentResponse[UploadedFile])
def delete(file_id:UUID,actor:Actor,client:SDK):
    return {'data':FileRepository(client).action(actor,'delete',file_id)}
