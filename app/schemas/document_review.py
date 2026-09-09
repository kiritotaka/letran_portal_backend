from datetime import datetime
from typing import get_args
from uuid import UUID
import re
from pydantic import BaseModel, Field, model_validator
from app.schemas.documents import Input
from app.schemas.analysis import FieldName

MONEY = {'contract_total', 'paid_amount', 'remaining_amount'}
DATES = {'acceptance_date', 'actual_start_date', 'actual_end_date', 'contract_date'}
OPTIONAL = {'party_a_phone', 'party_b_phone'}


class ReviewField(Input):
    name: FieldName
    value: str | None = Field(max_length=6000)

    @model_validator(mode='after')
    def validate_value(self):
        if self.value is None or not self.value.strip():
            self.value = None
            return self
        self.value = self.value.strip()
        if any(ord(c) < 32 for c in self.value) or '{{' in self.value or '}}' in self.value:
            raise ValueError('Use plain single-line values without template markers')
        if self.name in MONEY:
            if not re.fullmatch(r'[0-9]{1,18}', self.value):
                raise ValueError('VND must be an unsigned integer string without separators')
            self.value = str(int(self.value))
        if self.name in {'copy_count', 'copies_per_party'}:
            if not re.fullmatch(r'[0-9]{1,3}', self.value) or not 1 <= int(self.value) <= 100:
                raise ValueError('Copies must be between 1 and 100')
            self.value = str(int(self.value))
        if self.name in DATES:
            if not re.fullmatch(r'[0-9]{2}/[0-9]{2}/[0-9]{4}', self.value):
                raise ValueError('Dates must use DD/MM/YYYY')
            datetime.strptime(self.value, '%d/%m/%Y')
        return self


class SaveReview(Input):
    analysis_job_id: UUID
    expected_revision: int = Field(ge=0, strict=True)
    confirmed: bool = Field(strict=True)
    fields: list[ReviewField] = Field(min_length=24, max_length=24)

    @model_validator(mode='after')
    def complete_snapshot(self):
        values = {f.name: f.value for f in self.fields}
        if len(values) != 24 or set(values) != set(get_args(FieldName)):
            raise ValueError('Provide each of the 24 fields exactly once')
        if values['actual_start_date'] and values['actual_end_date']:
            if datetime.strptime(values['actual_start_date'], '%d/%m/%Y') > datetime.strptime(values['actual_end_date'], '%d/%m/%Y'):
                raise ValueError('Actual start date must not follow end date')
        if values['copy_count'] and values['copies_per_party']:
            if int(values['copies_per_party']) > int(values['copy_count']):
                raise ValueError('Copies per party exceed total')
        if self.confirmed and any(not value for name, value in values.items() if name not in OPTIONAL):
            raise ValueError('Complete required fields before confirming')
        return self


class ReviewData(BaseModel):
    id: UUID
    request_id: UUID
    analysis_job_id: UUID
    revision: int
    confirmed: bool
    fields: list[ReviewField]
    template_id: UUID
    created_by: UUID
    created_at: datetime


class ExportInput(Input):
    revision: int = Field(ge=1, strict=True)


class ExportData(Input):
    review_id: UUID
    revision: int
    filename: str
    download_url: str
    expires_in: int = 300
