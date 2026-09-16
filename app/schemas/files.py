from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel


class UploadedFile(BaseModel):
    id: UUID
    purpose: str
    original_name: str
    content_type: str
    size_bytes: int
    status: Literal['uploading','ready','deleted']
    created_by: UUID
    created_at: datetime
    updated_at: datetime


class FileDownload(BaseModel):
    file_id: UUID
    download_url: str
    expires_in: int
