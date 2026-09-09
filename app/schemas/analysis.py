from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field, model_validator

FieldName = Literal['acceptance_date','acceptance_place','acceptance_statement','actual_end_date',
 'actual_start_date','contract_date','contract_number','contract_total','copies_per_party','copy_count',
 'paid_amount','party_a_address','party_a_name','party_a_phone','party_a_position','party_a_representative',
 'party_b_address','party_b_name','party_b_phone','party_b_position','party_b_representative',
 'remaining_amount','service_description','service_quality']


class Evidence(BaseModel):
    model_config = ConfigDict(extra='forbid')
    file_id: UUID
    location: str = Field(min_length=1,max_length=200)
    quote: str = Field(min_length=1,max_length=1500)


class ExtractedField(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: FieldName
    value: str | None = Field(max_length=6000)
    sources: list[Evidence] = Field(max_length=10)
    conflict: bool
    basis: Literal['explicit', 'actual_confirmed', 'target_report', 'planned', 'unknown'] = 'unknown'


class ModelExtraction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    fields: list[ExtractedField] = Field(max_length=24)

    @model_validator(mode='after')
    def unique_fields(self):
        if len({f.name for f in self.fields})!=len(self.fields):
            raise ValueError('Duplicate extraction fields')
        return self


class ReviewedField(ExtractedField):
    status: Literal['extracted','missing','needs_input','conflict']


class ExtractionResult(BaseModel):
    fields: list[ReviewedField]
    missing_fields: list[FieldName]
    warnings: list[str]
    requires_review: Literal[True] = True


class SourceInfo(BaseModel):
    file_id: UUID
    original_name: str
    document_id: UUID
    document_title: str
    document_type: str
    sort_order: int


class JobItem(BaseModel):
    id: UUID
    request_id: UUID
    created_by: UUID
    status: Literal['queued','processing','completed','failed']
    stage: str
    model: str
    schema_version: str
    source_snapshot: list[SourceInfo]
    extracted_data: ExtractionResult | None = None
    error_code: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
