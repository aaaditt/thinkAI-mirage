"""Builds the full replay timeline once and caches it in data/.

Two flood runs are kept apart on purpose:
- "truth": the surrogate driven by the recorded rain. Only the simulated sensors
  read it. It stands in for what really happened; it is NOT observed flood data.
- "model": the surrogate driven by its own 1-hour rain forecast, then pulled
  toward the sensor readings each hour. This is what the screen shows.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, fields
from typing import Any

import numpy as np

from app import config
from app.config import GRID, Grid
from app.ground import (
    SegmentIndex,
    Terrain,
    blend_toward_sensors,
    build_segment_index,
    build_terrain,
    load_elevation,
    load_road_features,
    segment_depths,
    step,
)
from app.sensors import Sensor, SimulatedDepthSensors, place_sensors
from app.sky import RainSource, load_rain_source, story_zero_hour


@dataclass(frozen=True)
class Timeline:
    """Per-hour results. H hours, L forecast leads, N road segments, S sensors."""

    rain_small: np.ndarray  # (H, r, c) recorded rain, block means, mm
    forecast_small: np.ndarray  # (H, L, r, c) simulated rain forecast, mm
    segment_model_cm: np.ndarray  # (H, N) model depth before sensor correction
    segment_cm: np.ndarray  # (H, N) model depth after sensor correction
    segment_forecast_cm: np.ndarray  # (H, L, N) forecast depth for +1..+L h
    sensor_cm: np.ndarray  # (H, S) simulated sensor readings


@dataclass(frozen=True)
class Scenario:
    """The fixed inputs of the replay: everything except human decisions."""

    grid: Grid
    features: list[dict[str, Any]]
    terrain: Terrain
    index: SegmentIndex
    source: RainSource
    sensors: list[Sensor]
    hours: int
    zero_hour: int


@dataclass(frozen=True)
class World:
    """A scenario and its baseline timeline (no actions approved)."""

    scenario: Scenario
    timeline: Timeline


def block_mean(field: np.ndarray, block: int) -> np.ndarray:
    """Mean over block x block cells on the last two axes (edge blocks may be smaller)."""
    rows = np.arange(0, field.shape[-2], block)
    cols = np.arange(0, field.shape[-1], block)
    sums = np.add.reduceat(np.add.reduceat(field, rows, axis=-2), cols, axis=-1)
    ones = np.ones(field.shape[-2:])
    counts = np.add.reduceat(np.add.reduceat(ones, rows, axis=0), cols, axis=1)
    return sums / counts


def drainage_by_hour(scenario: Scenario, extra_cm: np.ndarray | None) -> np.ndarray:
    """Drainage (cm/h) per hour and cell: the base rate plus any staged pumps."""
    base = np.full((scenario.hours, *scenario.grid.shape), config.DRAINAGE_CM_PER_HOUR)
    return base if extra_cm is None else base + extra_cm


def truth_depths(scenario: Scenario, drainage: np.ndarray) -> np.ndarray:
    """Depth (cm) at the end of each hour under the recorded rain."""
    depth = np.zeros(scenario.grid.shape)
    out = []
    for hour in range(scenario.hours):
        depth, _ = step(depth, scenario.source.truth(hour), scenario.terrain, drainage[hour])
        out.append(depth)
    return np.array(out)


def forecast_segment_depths(
    scenario: Scenario, state_cm: np.ndarray, forecasts: list[np.ndarray],
    drainage: np.ndarray, hour: int,
) -> np.ndarray:
    """Run the model forward on forecast rain; depth per segment for each lead."""
    depth, out = state_cm, []
    for lead, rain in enumerate(forecasts, start=1):
        target = min(hour + lead, scenario.hours - 1)
        depth, _ = step(depth, rain, scenario.terrain, drainage[target])
        out.append(segment_depths(depth, scenario.index, scenario.terrain.dip_cm))
    return np.array(out)


def build_timeline(scenario: Scenario, extra_drainage_cm: np.ndarray | None = None) -> Timeline:
    """Run the whole day. `extra_drainage_cm` (hours, rows, cols) comes only from
    APPROVED pump actions; with None the result is the no-action baseline."""
    source, terrain, index = scenario.source, scenario.terrain, scenario.index
    drainage = drainage_by_hour(scenario, extra_drainage_cm)
    gauge = SimulatedDepthSensors(truth_depths(scenario, drainage), scenario.sensors)
    rows = np.array([s.row for s in scenario.sensors])
    cols = np.array([s.col for s in scenario.sensors])
    leads = range(1, config.FORECAST_LEADS + 1)

    state = np.zeros(scenario.grid.shape)
    # Hour 0 has no earlier forecast to run on, so it starts from the record.
    estimated_rain = source.truth(0)
    out: dict[str, list[np.ndarray]] = {f.name: [] for f in fields(Timeline)}
    for hour in range(scenario.hours):
        model, _ = step(state, estimated_rain, terrain, drainage[hour])
        readings = np.array([r.depth_cm for r in gauge.read(hour)])
        state = blend_toward_sensors(model, rows, cols, readings)
        forecasts = [source.forecast(hour, lead) for lead in leads]

        out["rain_small"].append(block_mean(source.truth(hour), config.RAIN_DOWNSAMPLE))
        out["forecast_small"].append(block_mean(np.array(forecasts), config.RAIN_DOWNSAMPLE))
        out["segment_model_cm"].append(segment_depths(model, index, terrain.dip_cm))
        out["segment_cm"].append(segment_depths(state, index, terrain.dip_cm))
        out["segment_forecast_cm"].append(
            forecast_segment_depths(scenario, state, forecasts, drainage, hour)
        )
        out["sensor_cm"].append(readings)
        estimated_rain = forecasts[0]
    return Timeline(**{name: np.array(v, dtype=np.float32) for name, v in out.items()})


# ---------------------------------------------------------------- cache


def cache_signature() -> str:
    """Changes whenever a setting or input file that affects the timeline changes."""
    settings = {
        name: value
        for name, value in vars(config).items()
        if name.isupper() and isinstance(value, (int, float, str))
    }
    inputs = [
        (path.name, path.stat().st_size, path.stat().st_mtime_ns)
        for path in (config.RAIN_TRUTH_PATH, config.ELEVATION_PATH, config.ROADS_PATH)
    ]
    blob = json.dumps([settings, inputs], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()


def load_cached_timeline(signature: str) -> Timeline | None:
    if not config.TIMELINE_PATH.exists():
        return None
    with np.load(config.TIMELINE_PATH) as saved:
        if str(saved["signature"]) != signature:
            return None
        return Timeline(**{f.name: saved[f.name] for f in fields(Timeline)})


def load_scenario() -> Scenario:
    features = load_road_features()
    terrain = build_terrain(load_elevation(), features, GRID)
    source = load_rain_source()
    return Scenario(
        grid=GRID,
        features=features,
        terrain=terrain,
        index=build_segment_index(features, GRID),
        source=source,
        sensors=place_sensors(
            features, GRID, ~terrain.open_water, np.random.default_rng(config.SEED)
        ),
        hours=config.HOURS,
        zero_hour=story_zero_hour(source),
    )


def load_world() -> World:
    """Load the cached inputs and baseline timeline, rebuilding it if it is stale."""
    scenario = load_scenario()
    signature = cache_signature()
    timeline = load_cached_timeline(signature)
    if timeline is None:
        timeline = build_timeline(scenario)
        np.savez_compressed(config.TIMELINE_PATH, signature=signature, **asdict(timeline))
    return World(scenario=scenario, timeline=timeline)
