"""FastAPI app: serves the precomputed replay. Run from backend/:

    uvicorn app.main:app --port 8000
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware

from app import config
from app.city import ActionError, Planner, Session
from app.ground import risk_class
from app.models import (
    Action,
    DecidedBy,
    District,
    Meta,
    PlanResult,
    Policy,
    ReplayFrame,
    RiskCounts,
    SensorReading,
    StoryWindow,
    Thresholds,
)
from app.replay import World, load_world


def digits(classes: np.ndarray) -> str:
    """Risk classes 0/1/2 -> one character per road segment."""
    return (classes.astype(np.uint8) + ord("0")).tobytes().decode("ascii")


def flat_mm(grid_mm: np.ndarray) -> list[float]:
    return [round(float(v), 1) for v in grid_mm.ravel()]


def roads_json(world: World) -> bytes:
    """Road GeoJSON with each feature's id set to its position in the risk strings."""
    collection = {
        "type": "FeatureCollection",
        "features": [
            {**feature, "id": number}
            for number, feature in enumerate(world.scenario.features)
        ],
    }
    return json.dumps(collection, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def build_meta(session: Session) -> Meta:
    world = session.world
    grid, timeline, zero = world.scenario.grid, world.timeline, world.scenario.zero_hour
    return Meta(
        disclaimer=config.DISCLAIMER,
        date=config.REPLAY_DATE,
        timezone=config.TIMEZONE,
        hours=timeline.segment_cm.shape[0],
        bbox=(grid.lon_min, grid.lat_min, grid.lon_max, grid.lat_max),
        grid_rows=grid.rows,
        grid_cols=grid.cols,
        rain_rows=timeline.rain_small.shape[1],
        rain_cols=timeline.rain_small.shape[2],
        rain_block=config.RAIN_DOWNSAMPLE,
        forecast_leads=config.FORECAST_LEADS,
        segment_count=len(world.scenario.features),
        story=StoryWindow(
            zero_hour=zero,
            start_hour=zero - config.STORY_HOURS_BEFORE,
            end_hour=zero + config.STORY_HOURS_AFTER,
        ),
        thresholds=Thresholds(
            caution_cm=config.CAUTION_DEPTH_CM,
            impassable_cm=config.IMPASSABLE_DEPTH_CM,
            display_cap_cm=config.DISPLAY_DEPTH_CAP_CM,
        ),
        districts=[
            District(name=name, lat=lat, lon=lon) for name, (lat, lon) in config.DISTRICTS.items()
        ],
        policies=session.policies,
    )


def build_frame(session: Session, hour: int) -> ReplayFrame:
    scenario, timeline = session.world.scenario, session.timeline
    classes = risk_class(timeline.segment_cm[hour])
    counts = np.bincount(classes, minlength=3)
    payouts = session.payouts(hour)
    return ReplayFrame(
        hour=hour,
        offset_hours=hour - scenario.zero_hour,
        rain_mm=flat_mm(timeline.rain_small[hour]),
        rain_forecast_mm=[flat_mm(lead) for lead in timeline.forecast_small[hour]],
        risk=digits(classes),
        risk_uncorrected=digits(risk_class(timeline.segment_model_cm[hour])),
        risk_next_6h=digits(risk_class(timeline.segment_forecast_cm[hour].max(axis=0))),
        counts=RiskCounts(
            clear=int(counts[0]), caution=int(counts[1]), impassable=int(counts[2])
        ),
        sensors=[
            SensorReading(
                id=s.id, lat=s.lat, lon=s.lon, at_underpass=s.at_underpass,
                depth_cm=round(float(cm), 1),
            )
            for s, cm in zip(scenario.sensors, timeline.sensor_cm[hour])
        ],
        actions=session.actions,
        closed_segments=session.closed_segments(hour),
        alerts=session.alerts(hour),
        pumps_available=session.situation(hour).inventory.pumps_available,
        payouts=payouts,
        payout_total_aed=sum(event.amount_aed for event in payouts),
    )


def check_hour(session: Session, hour: int) -> None:
    if not 0 <= hour < session.world.scenario.hours:
        raise HTTPException(status_code=404, detail="hour is outside the replay window")


def create_app(
    world: World | None = None, planner: Planner | None = None,
    policies: list[Policy] | None = None,
) -> FastAPI:
    """Build the app. Pass a `world` in tests; otherwise it is loaded from data/."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.session = Session(world or load_world(), planner, policies)
        app.state.roads = roads_json(app.state.session.world)
        yield

    app = FastAPI(title="Mirage (prototype)", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"],
        allow_headers=["*"],
    )

    def decide(request: Request, action_id: str, approve: bool, by: DecidedBy) -> Action:
        try:
            return request.app.state.session.decide(action_id, approve, by)
        except ActionError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/meta")
    def meta(request: Request) -> Meta:
        return build_meta(request.app.state.session)

    @app.get("/api/roads")
    def roads(request: Request) -> Response:
        return Response(request.app.state.roads, media_type="application/geo+json")

    @app.get("/api/replay/{hour}")
    def replay(hour: int, request: Request) -> ReplayFrame:
        check_hour(request.app.state.session, hour)
        return build_frame(request.app.state.session, hour)

    @app.post("/api/plan/{hour}")
    def plan(hour: int, request: Request) -> PlanResult:
        """Ask the planner for proposals. They are queued as `proposed`, nothing more."""
        check_hour(request.app.state.session, hour)
        return request.app.state.session.plan(hour)

    @app.post("/api/actions/{action_id}/approve")
    def approve(action_id: str, request: Request, by: DecidedBy = "operator") -> Action:
        """`?by=demo_auto` is sent only by Demo mode, and is shown on the card."""
        return decide(request, action_id, approve=True, by=by)

    @app.post("/api/actions/{action_id}/reject")
    def reject(action_id: str, request: Request) -> Action:
        return decide(request, action_id, approve=False, by="operator")

    @app.post("/api/reset")
    def reset(request: Request) -> dict[str, bool]:
        request.app.state.session.reset()
        return {"ok": True}

    return app


app = create_app()
