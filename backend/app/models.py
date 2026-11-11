"""Pydantic schemas shared by the API routes."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


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
    policies: list[Policy]


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


# ---------------------------------------------------------------- City


class Evidence(BaseModel):
    forecast_depth_cm: float = Field(ge=0)
    lead_hours: int = Field(ge=0, le=6)
    confidence: float = Field(ge=0, le=1)


DecidedBy = Literal["operator", "demo_auto"]


class ProposedAction(BaseModel):
    """What a planner may output. Nothing here has any effect until approved."""

    type: Literal["stage_pump", "close_underpass", "area_alert", "open_road"]
    target: str  # a site id from the situation, or a district name for area_alert
    start_hour: int = Field(ge=0, le=23)
    reason: str = Field(min_length=1, max_length=300)
    evidence: Evidence
    message: str | None = None  # alert text; required for area_alert only


class Plan(BaseModel):
    actions: list[ProposedAction]


class Action(ProposedAction):
    """A proposal in the queue. Only a human decision changes `status`."""

    id: str
    status: Literal["proposed", "approved", "rejected"] = "proposed"
    # Who decided. "demo_auto" marks Demo mode's hands-free approvals, so the
    # screen can label them and never pass them off as an operator's decision.
    decided_by: DecidedBy | None = None
    label: str
    lat: float
    lon: float
    proposed_hour: int
    end_hour: int | None = None  # set on a closure when its road is reopened


class AtRiskSite(BaseModel):
    """A road or underpass (one OSM way) with its modelled outlook."""

    target: str
    label: str
    underpass: bool
    district: str | None
    depth_now_cm: float
    forecast_peak_cm: float
    peak_lead_hours: int
    impassable_lead_hours: int | None  # 0 = already impassable; None = not forecast


class DistrictOutlook(BaseModel):
    name: str
    impassable_now: int
    impassable_by_lead: list[int]  # for +1..+6 h
    deepest_now_cm: float
    deepest_forecast_cm: float


class Depot(BaseModel):
    name: str
    lat: float
    lon: float
    pumps: int
    tankers: int


class Inventory(BaseModel):
    """MOCK resources. There is no real fleet behind these numbers."""

    pumps_total: int
    pumps_available: int
    tankers_total: int
    depots: list[Depot]


class Situation(BaseModel):
    """Everything a planner is given."""

    hour: int
    clock: str
    sites: list[AtRiskSite]
    closed_sites: list[AtRiskSite]  # outlook for underpasses currently closed
    districts: list[DistrictOutlook]
    inventory: Inventory
    actions: list[Action]  # every action so far, with its status


class PlanResult(BaseModel):
    planner: Literal["llm", "rules"]
    fallback_reason: str | None = None
    actions: list[Action]


class Alert(BaseModel):
    """An approved area alert. Shown in the app only; never sent anywhere."""

    action_id: str
    district: str
    message: str
    issued_hour: int


class Policy(BaseModel):
    """A MOCK parametric policy. The business, trigger and amount are invented."""

    id: str
    business: str
    district: str
    lat: float
    lon: float
    tier: str
    threshold_cm: float
    duration_hours: int  # consecutive hourly readings at or above the threshold
    amount_aed: int
    sensor_id: str  # the gauge this policy is indexed to
    sensor_distance_m: int  # gauge-to-business distance: the basis risk


class PayoutEvent(BaseModel):
    """Fired from measured (simulated sensor) depth only. No money moves anywhere."""

    policy_id: str
    hour: int
    measured_cm: float
    amount_aed: int


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
    actions: list[Action]  # the whole queue, every status
    closed_segments: list[int]  # road segments closed by an APPROVED action at this hour
    alerts: list[Alert]  # approved alerts issued up to this hour, newest last
    pumps_available: int
    payouts: list[PayoutEvent]  # every payout fired up to this hour, oldest first
    payout_total_aed: int
