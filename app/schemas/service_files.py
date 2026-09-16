from datetime import datetime
from typing import Generic, Literal, TypeVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class CreateServiceRequest(Input):
    title: str = Field(min_length=1, max_length=200)


class UpdateServiceRequest(Input):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    status: Literal["draft", "archived"] | None = None

    @model_validator(mode="after")
    def nonempty(self):
        if not self.model_fields_set or any(getattr(self, k) is None for k in self.model_fields_set):
            raise ValueError("Provide non-null fields to update")
        return self


class ServiceRequestItem(BaseModel):
    id: UUID
    title: str
    status: str
    created_by: UUID
    updated_by: UUID
    created_at: datetime
    updated_at: datetime


class ServiceFileItem(BaseModel):
    id: UUID
    request_id: UUID
    original_name: str
    content_type: str
    size_bytes: int
    status: Literal["uploading", "ready", "deleted"]
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    # Present only right after upload/refresh; signed URLs expire, so re-fetch via download-url.
    download_url: str | None = None
    expires_in: int | None = None


class DownloadData(BaseModel):
    file_id: UUID
    download_url: str
    expires_in: int = 300


T = TypeVar("T")


class ServiceFileResponse(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: T
