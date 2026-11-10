"""Pydantic schemas shared by the API routes."""

from __future__ import annotations

from pydantic import BaseModel


class District(BaseModel):
    name: str
    lat: float
    lon: float


class StoryWindow(BaseModel):
    """Hours of the replay day shown on the timeline, around the computed T-0."""

    zero_hour: int
    start_hour: int
    end_hour: int


class Thresholds(BaseModel):
    caution_cm: float
    impassable_cm: float
    display_cap_cm: float


class Meta(BaseModel):
    disclaimer: str
    date: str
    timezone: str
    hours: int
    bbox: tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max
    grid_rows: int
    grid_cols: int
    rain_rows: int
    rain_cols: int
    rain_block: int  # each rain value is the mean of a block of this many cells
    forecast_leads: int
    segment_count: int
    story: StoryWindow
    thresholds: Thresholds
    districts: list[District]


class RiskCounts(BaseModel):
    clear: int
    caution: int
    impassable: int


class SensorReading(BaseModel):
    """A SIMULATED depth reading. No real camera or gauge is behind it."""

    id: str
    lat: float
    lon: float
    at_underpass: bool
    depth_cm: float


class ReplayFrame(BaseModel):
    """Everything the screen needs for one hour.

    The three `risk*` fields hold one digit per road segment, in the order of
    /api/roads: 0 clear, 1 caution, 2 impassable.
    """

    hour: int
    offset_hours: int  # hour - T-0
    rain_mm: list[float]  # recorded rain this hour, rain_rows x rain_cols, row 0 = south
    rain_forecast_mm: list[list[float]]  # simulated forecast for +1..+6 h, same layout
    risk: str  # model estimate after the simulated sensor correction
    risk_uncorrected: str  # model estimate before the correction
    risk_next_6h: str  # worst class forecast over the next 6 hours
    counts: RiskCounts  # for `risk`
    sensors: list[SensorReading]
