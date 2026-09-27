from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PredictIn(BaseModel):
    month: str | None = None
    dosing_multiplier: float = Field(default=1.0, gt=0)
    volume_multiplier: float = Field(default=1.0, gt=0)
    temp_delta: float = 0.0
    precip_multiplier: float = Field(default=1.0, gt=0)
    overrides: dict[str, float] = Field(default_factory=dict)


class DosingIn(BaseModel):
    month: str | None = None
    dosing_multiplier: float | None = Field(default=None, gt=0)
    volume_multiplier: float = Field(default=1.0, gt=0)
    temp_delta: float = 0.0
    precip_multiplier: float = Field(default=1.0, gt=0)
    overrides: dict[str, float] = Field(default_factory=dict)
    target_bod: float | None = Field(default=None, gt=0)
    target_cod: float | None = Field(default=None, gt=0)


class DataIn(BaseModel):
    model_config = ConfigDict(extra="allow")

    month: str
    values: dict[str, float | int | None] | None = None


class RetrainIn(BaseModel):
    modules: list[str] = Field(default_factory=lambda: ["indicators", "dosing", "sediments"])
