from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import Field
from app.schemas.documents import Input
from app.schemas.lists import PaginationParams


class CreateProductImport(Input):
    file_id: UUID
    sheet_name: str | None = Field(default=None, min_length=1, max_length=31)


class ProductImportJob(Input):
    id: UUID
    file_id: UUID
    sheet_name: str | None
    status: Literal['queued', 'processing', 'preview_ready', 'failed']
    attempts: int
    summary: dict
    error_code: str | None
    created_by: UUID
    created_at: datetime
    updated_at: datetime
    finished_at: datetime | None


class PreviewFilters(PaginationParams):
    action: Literal['create', 'update', 'unchanged', 'error'] | None = None


class PreviewRow(Input):
    row_number: int
    source_row: int
    product_code: str
    product_name: str
    occurrences: int
    action: Literal['create', 'update', 'unchanged', 'error']
    error_code: str | None
    existing: dict | None
