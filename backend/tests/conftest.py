"""A tiny synthetic world, so API and replay tests never touch data/ or the network."""

from __future__ import annotations

import numpy as np
import pytest

from app import config
from app.config import Grid
from app.ground import build_segment_index, build_terrain
from app.replay import Scenario, World, build_timeline
from app.sensors import place_sensors
from app.sky import HistoricalRainSource, story_zero_hour

SMALL_GRID = Grid(lat_min=25.0, lat_max=25.1, lon_min=55.0, lon_max=55.1, rows=10, cols=10)


def row_road(row: int, underpass: bool = False, bridge: bool = False) -> dict:
    lat = 25.005 + 0.01 * row
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": [[55.001, lat], [55.099, lat]]},
        "properties": {
            "id": 1000 + row, "name": f"Road {row}", "highway": "primary",
            "underpass": underpass, "bridge": bridge,
        },
    }


@pytest.fixture(scope="session")
def small_world() -> World:
    rng = np.random.default_rng(3)
    rain = rng.uniform(0.0, 12.0, (config.HOURS, *SMALL_GRID.shape))
    rain[14] += 60.0  # one clearly wettest hour inside the story window
    rows, cols = np.indices(SMALL_GRID.shape)
    elevation = 1.0 + 0.2 * np.hypot(rows - 5, cols - 5)
    elevation[0, 0] = 0.0  # one open-water cell
    features = [row_road(r) for r in range(8)] + [
        row_road(8, underpass=True), row_road(9, bridge=True)
    ]
    terrain = build_terrain(elevation, features, SMALL_GRID)
    source = HistoricalRainSource(rain)
    sensors = place_sensors(
        features, SMALL_GRID, ~terrain.open_water, np.random.default_rng(0)
    )
    scenario = Scenario(
        grid=SMALL_GRID,
        features=features,
        terrain=terrain,
        index=build_segment_index(features, SMALL_GRID),
        source=source,
        sensors=sensors,
        hours=config.HOURS,
        zero_hour=story_zero_hour(source),
    )
    return World(scenario=scenario, timeline=build_timeline(scenario))
