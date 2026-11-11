"""Simulated depth sensors: the independent index that Shield payouts read.

There are no real cameras or gauges behind this. Each reading is the simulated
"what really happened" depth at the sensor's cell, plus seeded measurement noise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import numpy as np

from app import config
from app.config import Grid
from app.ground import Terrain, line_cells


@dataclass(frozen=True)
class Sensor:
    id: str
    lat: float
    lon: float
    row: int
    col: int
    at_underpass: bool
    district: str | None = None  # set for the Shield index gauges


@dataclass(frozen=True)
class Reading:
    sensor_id: str
    hour: int
    depth_cm: float


class DepthSensorSource(Protocol):
    """Where measured depths come from. Real gauges could implement this later."""

    def sensors(self) -> list[Sensor]: ...

    def read(self, hour: int) -> list[Reading]: ...


def hollowness(elevation_m: np.ndarray) -> np.ndarray:
    """How far each cell sits below the average of its 8 neighbours (m)."""
    padded = np.pad(elevation_m, 1, mode="edge")
    rows, cols = elevation_m.shape
    around = sum(
        padded[1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + cols]
        for dr in (-1, 0, 1) for dc in (-1, 0, 1) if (dr, dc) != (0, 0)
    )
    return around / 8.0 - elevation_m


def district_low_points(
    road_cells: set[int], grid: Grid, ground_m: np.ndarray, centre: tuple[float, float],
    count: int,
) -> list[int]:
    """The `count` most hollow road cells within the district radius.

    Gauges go where water would collect. This uses terrain only, never flood results.
    """
    cells = np.array(sorted(road_cells))
    lats, lons = grid.lats()[cells // grid.cols], grid.lons()[cells % grid.cols]
    dy = (lats - centre[0]) * config.METRES_PER_DEG_LAT
    dx = (lons - centre[1]) * config.METRES_PER_DEG_LAT * np.cos(np.radians(centre[0]))
    nearby = cells[np.hypot(dx, dy) <= config.DISTRICT_RADIUS_KM * 1000.0]
    depth = hollowness(ground_m).ravel()[nearby]
    return [int(c) for c in nearby[np.argsort(-depth, kind="stable")[:count]]]


def place_sensors(
    features: list[dict[str, Any]], grid: Grid, terrain: Terrain, rng: np.random.Generator,
    districts: dict[str, tuple[float, float]] | None = None,
) -> list[Sensor]:
    """Pick sensor cells on roads: underpasses, district low points, then other roads.

    Sensors are never put on open water or on bridges.
    """
    districts = config.DISTRICTS if districts is None else districts
    land = ~terrain.open_water
    underpass_cells: set[int] = set()
    road_cells: set[int] = set()
    for feature in features:
        if feature["properties"]["bridge"]:
            continue
        cells = [int(c) for c in line_cells(feature["geometry"]["coordinates"], grid)
                 if land.flat[c]]
        (underpass_cells if feature["properties"]["underpass"] else road_cells).update(cells)
    road_cells -= underpass_cells

    def pick(cells: set[int], count: int) -> list[int]:
        pool = np.array(sorted(cells))
        return [int(c) for c in rng.choice(pool, size=min(count, pool.size), replace=False)]

    chosen: list[tuple[int, str | None]] = [
        (cell, None) for cell in pick(underpass_cells, config.SENSOR_UNDERPASS_COUNT)
    ]
    ground_m = terrain.elevation_m + terrain.dip_cm / 100.0  # ignore the assumed dips
    for name, centre in districts.items():
        taken = {cell for cell, _ in chosen}
        low = district_low_points(road_cells - taken, grid, ground_m, centre,
                                  config.SENSOR_PER_DISTRICT)
        chosen += [(cell, name) for cell in low]
    taken = {cell for cell, _ in chosen}
    chosen += [(cell, None) for cell in pick(road_cells - taken,
                                             config.SENSOR_COUNT - len(chosen))]
    lats, lons = grid.lats(), grid.lons()
    return [
        Sensor(
            id=f"S{number:03d}",
            lat=round(float(lats[cell // grid.cols]), 5),
            lon=round(float(lons[cell % grid.cols]), 5),
            row=cell // grid.cols,
            col=cell % grid.cols,
            at_underpass=cell in underpass_cells,
            district=district,
        )
        for number, (cell, district) in enumerate(chosen, start=1)
    ]


class SimulatedDepthSensors:
    """DepthSensorSource that samples a simulated truth and adds noise."""

    def __init__(self, truth_depth_cm: np.ndarray, sensors: list[Sensor],
                 seed: int = config.SEED):
        self._truth = truth_depth_cm  # (hours, rows, cols)
        self._sensors = sensors
        self._seed = seed

    def sensors(self) -> list[Sensor]:
        return self._sensors

    def read(self, hour: int) -> list[Reading]:
        rng = np.random.default_rng([self._seed, 1, hour])
        rows = np.array([s.row for s in self._sensors])
        cols = np.array([s.col for s in self._sensors])
        true_cm = self._truth[hour, rows, cols]
        noisy = (
            true_cm * (1.0 + config.SENSOR_RELATIVE_NOISE * rng.standard_normal(true_cm.size))
            + config.SENSOR_ABSOLUTE_NOISE_CM * rng.standard_normal(true_cm.size)
        )
        return [
            Reading(sensor_id=s.id, hour=hour, depth_cm=round(max(0.0, float(v)), 1))
            for s, v in zip(self._sensors, noisy)
        ]
