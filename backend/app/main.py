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
from app.ground import risk_class
from app.models import (
    District,
    Meta,
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
        "features": [{**feature, "id": number} for number, feature in enumerate(world.features)],
    }
    return json.dumps(collection, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def build_meta(world: World) -> Meta:
    grid, timeline = world.grid, world.timeline
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
        segment_count=len(world.features),
        story=StoryWindow(
            zero_hour=world.zero_hour,
            start_hour=world.zero_hour - config.STORY_HOURS_BEFORE,
            end_hour=world.zero_hour + config.STORY_HOURS_AFTER,
        ),
        thresholds=Thresholds(
            caution_cm=config.CAUTION_DEPTH_CM,
            impassable_cm=config.IMPASSABLE_DEPTH_CM,
            display_cap_cm=config.DISPLAY_DEPTH_CAP_CM,
        ),
        districts=[
            District(name=name, lat=lat, lon=lon) for name, (lat, lon) in config.DISTRICTS.items()
        ],
    )


def build_frame(world: World, hour: int) -> ReplayFrame:
    timeline = world.timeline
    classes = risk_class(timeline.segment_cm[hour])
    counts = np.bincount(classes, minlength=3)
    return ReplayFrame(
        hour=hour,
        offset_hours=hour - world.zero_hour,
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
            for s, cm in zip(world.sensors, timeline.sensor_cm[hour])
        ],
    )


def create_app(world: World | None = None) -> FastAPI:
    """Build the app. Pass a `world` in tests; otherwise it is loaded from data/."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.world = world or load_world()
        app.state.roads = roads_json(app.state.world)
        yield

    app = FastAPI(title="Mirage (prototype)", lifespan=lifespan)
    app.add_middleware(GZipMiddleware, minimum_size=1000)
    app.add_middleware(
        CORSMiddleware, allow_origins=config.CORS_ORIGINS, allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/meta")
    def meta(request: Request) -> Meta:
        return build_meta(request.app.state.world)

    @app.get("/api/roads")
    def roads(request: Request) -> Response:
        return Response(request.app.state.roads, media_type="application/geo+json")

    @app.get("/api/replay/{hour}")
    def replay(hour: int, request: Request) -> ReplayFrame:
        current: World = request.app.state.world
        if not 0 <= hour < current.timeline.segment_cm.shape[0]:
            raise HTTPException(status_code=404, detail="hour is outside the replay window")
        return build_frame(current, hour)

    return app


app = create_app()
