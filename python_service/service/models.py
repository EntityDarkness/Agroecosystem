from datetime import datetime, timezone

from sqlalchemy import JSON, Boolean, CheckConstraint, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from service.database import Base


def utcnow():
    return datetime.now(timezone.utc)


class ControlPoint(Base):
    __tablename__ = "control_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    description: Mapped[str] = mapped_column(String(1000), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    indicators: Mapped[list["Indicator"]] = relationship(back_populates="point")


class Indicator(Base):
    __tablename__ = "indicators"
    __table_args__ = (CheckConstraint("min_value <= max_value OR max_value IS NULL", name="ck_indicator_range"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(180), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    unit: Mapped[str] = mapped_column(String(40))
    medium: Mapped[str] = mapped_column(String(20))
    point_id: Mapped[int] = mapped_column(ForeignKey("control_points.id", ondelete="RESTRICT"))
    min_value: Mapped[float] = mapped_column(Float, default=0)
    max_value: Mapped[float | None] = mapped_column(Float, nullable=True)
    norm: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    point: Mapped[ControlPoint] = relationship(back_populates="indicators")
    measurements: Mapped[list["Measurement"]] = relationship(back_populates="indicator")


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (UniqueConstraint("month", "indicator_id", name="uq_measurement_month_indicator"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7))
    indicator_id: Mapped[int] = mapped_column(ForeignKey("indicators.id", ondelete="RESTRICT"))
    value: Mapped[float] = mapped_column(Float)
    comment: Mapped[str] = mapped_column(String(1000), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    indicator: Mapped[Indicator] = relationship(back_populates="measurements")


class ModelMonth(Base):
    """Imported monthly weather and auxiliary features used by existing ML models."""
    __tablename__ = "model_months"
    month: Mapped[str] = mapped_column(String(7), primary_key=True)
    values: Mapped[dict] = mapped_column(JSON)


class SourceDataset(Base):
    """Archived source tables, imported once, including dosing calibration data."""
    __tablename__ = "source_datasets"
    name: Mapped[str] = mapped_column(String(100), primary_key=True)
    rows: Mapped[list] = mapped_column(JSON)


# Migration 2 creates these indexes explicitly; existing databases get them too.
QUERY_INDEXES = [
    Index("ix_point_active_name", ControlPoint.active, ControlPoint.name),
    Index("ix_indicator_point_medium", Indicator.point_id, Indicator.medium),
    Index("ix_indicator_medium_name", Indicator.medium, Indicator.name),
    Index("ix_measurement_indicator_month", Measurement.indicator_id, Measurement.month),
    Index("ix_measurement_month_value", Measurement.month, Measurement.value),
]
