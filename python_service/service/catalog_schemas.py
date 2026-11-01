from datetime import datetime, timezone
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)

class PointCreate(Input):
    code: str = Field(min_length=2, max_length=30)
    name: str = Field(min_length=2, max_length=160)
    description: str = Field(default="", max_length=1000)
    active: bool = True


class PointUpdate(Input):
    code: str | None = Field(default=None, min_length=2, max_length=30)
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    active: bool | None = None


class IndicatorCreate(Input):
    code: str = Field(min_length=2, max_length=180)
    name: str = Field(min_length=2, max_length=200)
    unit: str = Field(min_length=1, max_length=40)
    medium: Literal["water", "sediments", "operation"]
    point_id: int = Field(gt=0)
    min_value: float = 0
    max_value: float | None = None
    norm: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def range_order(self):
        if self.max_value is not None and self.max_value < self.min_value:
            raise ValueError("Верхняя граница меньше нижней")
        return self


class IndicatorUpdate(Input):
    code: str | None = Field(default=None, min_length=2, max_length=180)
    name: str | None = Field(default=None, min_length=2, max_length=200)
    unit: str | None = Field(default=None, min_length=1, max_length=40)
    medium: Literal["water", "sediments", "operation"] | None = None
    point_id: int | None = Field(default=None, gt=0)
    min_value: float | None = None
    max_value: float | None = None
    norm: float | None = Field(default=None, ge=0)


class MeasurementCreate(Input):
    month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$", min_length=7, max_length=7)
    indicator_id: int = Field(gt=0)
    value: float
    comment: str = Field(default="", max_length=1000)

    @field_validator("month")
    @classmethod
    def month_valid(cls, value):
        parsed = datetime.strptime(value, "%Y-%m")
        if not 1900 <= parsed.year <= 2200:
            raise ValueError("Месяц должен быть в диапазоне 1900–2200")
        return value


class MeasurementUpdate(Input):
    month: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    indicator_id: int | None = Field(default=None, gt=0)
    value: float | None = None
    comment: str | None = Field(default=None, max_length=1000)


class ORMOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    created_at: datetime


class PointOut(PointCreate, ORMOut):
    pass


class IndicatorOut(IndicatorCreate, ORMOut):
    pass


class MeasurementOut(MeasurementCreate, ORMOut):
    indicator_name: str
    point_name: str
    unit: str
    norm: float | None
    exceeds_norm: bool | None


T = TypeVar("T")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int
    page: int
    per_page: int
    total_pages: int


class ListQuery(Input):
    page: int = Field(default=1, ge=1)
    per_page: int = Field(default=10, ge=1, le=100)
    sort_by: str = "id"
    sort_order: Literal["asc", "desc"] = "asc"
    search: str | None = Field(default=None, min_length=2, max_length=200)
    code: str | None = None
    active: bool | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    point_id: int | None = Field(default=None, gt=0)
    indicator_id: int | None = Field(default=None, gt=0)
    medium: Literal["water", "sediments", "operation"] | None = None
    unit: str | None = None
    has_norm: bool | None = None
    month_from: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    month_to: str | None = Field(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    min_value: float | None = None
    max_value: float | None = None
    exceeds_norm: bool | None = None

    @field_validator("created_from", "created_to")
    @classmethod
    def normalize_time(cls, value):
        # SQLite stores UTC timestamps without a zone suffix.
        if value is not None and value.tzinfo is not None:
            return value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    @model_validator(mode="after")
    def ranges(self):
        for lo, hi in [(self.month_from, self.month_to), (self.min_value, self.max_value), (self.created_from, self.created_to)]:
            if lo is not None and hi is not None and lo > hi:
                raise ValueError("Начало диапазона больше конца")
        return self
