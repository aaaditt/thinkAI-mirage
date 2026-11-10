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
from app.ground import line_cells


@dataclass(frozen=True)
class Sensor:
    id: str
    lat: float
    lon: float
    row: int
    col: int
    at_underpass: bool


@dataclass(frozen=True)
class Reading:
    sensor_id: str
    hour: int
    depth_cm: float


class DepthSensorSource(Protocol):
    """Where measured depths come from. Real gauges could implement this later."""

    def sensors(self) -> list[Sensor]: ...

    def read(self, hour: int) -> list[Reading]: ...


def place_sensors(
    features: list[dict[str, Any]], grid: Grid, land: np.ndarray, rng: np.random.Generator
) -> list[Sensor]:
    """Pick sensor cells on roads: some at underpasses, the rest on other roads.

    `land` is a boolean (rows, cols) mask; sensors are never put on open water.
    """
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

    chosen_underpass = pick(underpass_cells, config.SENSOR_UNDERPASS_COUNT)
    chosen_road = pick(road_cells, config.SENSOR_COUNT - len(chosen_underpass))
    lats, lons = grid.lats(), grid.lons()
    return [
        Sensor(
            id=f"S{number:03d}",
            lat=round(float(lats[cell // grid.cols]), 5),
            lon=round(float(lons[cell % grid.cols]), 5),
            row=cell // grid.cols,
            col=cell % grid.cols,
            at_underpass=cell in underpass_cells,
        )
        for number, cell in enumerate(chosen_underpass + chosen_road, start=1)
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
