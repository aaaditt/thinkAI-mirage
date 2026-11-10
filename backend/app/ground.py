"""Ground engine: a simplified flood surrogate. This is NOT a hydraulic model.

Each hour: add rain, let water run to the lowest neighbouring cell a few times,
remove a fixed drainage amount, never go below zero.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np

from app import config
from app.config import Grid

NEIGHBOUR_OFFSETS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


@dataclass(frozen=True)
class WaterBalance:
    """Water bookkeeping for one hour, in cm summed over cells."""

    stored_before: float
    rain_in: float
    drained: float
    to_open_water: float
    stored_after: float

    @property
    def error(self) -> float:
        expected = self.stored_before + self.rain_in - self.drained - self.to_open_water
        return self.stored_after - expected


# ---------------------------------------------------------------- water movement


def route_once(depth_cm: np.ndarray, elevation_m: np.ndarray, fraction: float) -> np.ndarray:
    """One D8 sub-step: each cell sends water to its lowest neighbour.

    Lowest means lowest water surface (ground + depth). A cell sends at most
    `fraction` of its water, and never more than half the surface difference,
    so two cells level out instead of swapping. Water never leaves the grid.
    """
    rows, cols = depth_cm.shape
    surface = elevation_m * 100.0 + depth_cm
    padded = np.pad(surface, 1, constant_values=np.inf)
    neighbours = np.stack(
        [padded[1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + cols] for dr, dc in NEIGHBOUR_OFFSETS]
    )
    target = neighbours.argmin(axis=0)
    drop = surface - neighbours.min(axis=0)
    outflow = np.clip(np.minimum(depth_cm * fraction, drop / 2.0), 0.0, None)

    inflow = np.zeros((rows + 2, cols + 2))
    for direction, (dr, dc) in enumerate(NEIGHBOUR_OFFSETS):
        inflow[1 + dr : 1 + dr + rows, 1 + dc : 1 + dc + cols] += np.where(
            target == direction, outflow, 0.0
        )
    return depth_cm - outflow + inflow[1:-1, 1:-1]


def step(
    depth_cm: np.ndarray,
    rain_mm: np.ndarray,
    elevation_m: np.ndarray,
    drainage_cm: np.ndarray | float = config.DRAINAGE_CM_PER_HOUR,
    substeps: int = config.ROUTING_SUBSTEPS,
    fraction: float = config.FLOW_FRACTION,
) -> tuple[np.ndarray, WaterBalance]:
    """Advance the flood state by one hour. Returns (new depth in cm, balance)."""
    open_water = elevation_m <= config.WATER_LEVEL_M
    stored_before = float(depth_cm.sum())
    rain_cm = rain_mm / 10.0
    depth = depth_cm + rain_cm

    to_open_water = 0.0
    for _ in range(substeps):
        depth = route_once(depth, elevation_m, fraction)
        to_open_water += float(depth[open_water].sum())
        depth[open_water] = 0.0

    drained = np.minimum(depth, drainage_cm)
    depth = depth - drained
    balance = WaterBalance(
        stored_before=stored_before,
        rain_in=float(rain_cm.sum()),
        drained=float(drained.sum()),
        to_open_water=to_open_water,
        stored_after=float(depth.sum()),
    )
    return depth, balance


def simulate(
    rain_mm: np.ndarray, elevation_m: np.ndarray
) -> tuple[np.ndarray, list[WaterBalance]]:
    """Run every hour of `rain_mm` (hours, rows, cols) from a dry start.

    Returns depth (cm) at the end of each hour, and the hourly water balance.
    """
    depth = np.zeros(elevation_m.shape)
    depths, balances = [], []
    for hour_rain in rain_mm:
        depth, balance = step(depth, hour_rain, elevation_m)
        depths.append(depth)
        balances.append(balance)
    return np.array(depths), balances


def blend_toward_sensors(
    depth_cm: np.ndarray,
    rows: np.ndarray,
    cols: np.ndarray,
    readings_cm: np.ndarray,
    weight: float = config.SENSOR_BLEND_WEIGHT,
) -> np.ndarray:
    """"Camera-corrected" depth: pull each sensor's cell toward its reading."""
    corrected = depth_cm.copy()
    corrected[rows, cols] = (1.0 - weight) * depth_cm[rows, cols] + weight * readings_cm
    return corrected


# ---------------------------------------------------------------- roads


@dataclass(frozen=True)
class SegmentIndex:
    """Which grid cells each road segment crosses, packed for fast lookups."""

    cells: np.ndarray  # flat cell indices, all segments concatenated
    starts: np.ndarray  # where each mapped segment begins in `cells`
    mapped: np.ndarray  # segment number for each entry of `starts`
    bridge: np.ndarray  # per segment: True if it is a bridge
    count: int


def line_cells(coords: list[list[float]], grid: Grid) -> np.ndarray:
    """Flat indices of the grid cells a (lon, lat) line passes through."""
    points = np.asarray(coords, dtype=float)
    lat_step = (grid.lat_max - grid.lat_min) / grid.rows
    lon_step = (grid.lon_max - grid.lon_min) / grid.cols
    # Walk the line in steps of half a cell so no crossed cell is skipped.
    along = np.concatenate([[0.0], np.cumsum(np.hypot(
        np.diff(points[:, 0]) / lon_step, np.diff(points[:, 1]) / lat_step))])
    samples = np.append(np.arange(0.0, along[-1], 0.5), along[-1])
    lons = np.interp(samples, along, points[:, 0])
    lats = np.interp(samples, along, points[:, 1])
    rows = np.floor((lats - grid.lat_min) / lat_step).astype(int)
    cols = np.floor((lons - grid.lon_min) / lon_step).astype(int)
    inside = (rows >= 0) & (rows < grid.rows) & (cols >= 0) & (cols < grid.cols)
    return np.unique(rows[inside] * grid.cols + cols[inside])


def build_segment_index(features: list[dict[str, Any]], grid: Grid) -> SegmentIndex:
    per_segment = [line_cells(f["geometry"]["coordinates"], grid) for f in features]
    mapped = np.array([i for i, cells in enumerate(per_segment) if cells.size], dtype=int)
    sizes = np.array([per_segment[i].size for i in mapped], dtype=int)
    return SegmentIndex(
        cells=np.concatenate([per_segment[i] for i in mapped]),
        starts=np.concatenate([[0], np.cumsum(sizes)[:-1]]).astype(int),
        mapped=mapped,
        bridge=np.array([f["properties"]["bridge"] for f in features], dtype=bool),
        count=len(features),
    )


def segment_depths(depth_cm: np.ndarray, index: SegmentIndex) -> np.ndarray:
    """Depth per road segment = deepest cell it crosses. Bridges are always 0:
    we assume the deck stays above the water."""
    out = np.zeros(index.count)
    out[index.mapped] = np.maximum.reduceat(depth_cm.ravel()[index.cells], index.starts)
    out[index.bridge] = 0.0
    return out


def risk_class(depth_cm: np.ndarray) -> np.ndarray:
    """0 = clear, 1 = caution, 2 = impassable."""
    return (
        (depth_cm >= config.CAUTION_DEPTH_CM).astype(int)
        + (depth_cm > config.IMPASSABLE_DEPTH_CM).astype(int)
    )


def peak_flood_hour(depths_by_segment: np.ndarray) -> int:
    """Story "T-0": the hour with the most impassable segments.

    Ties go to the hour with the greater total depth across segments.
    """
    impassable = (risk_class(depths_by_segment) == 2).sum(axis=1)
    totals = depths_by_segment.sum(axis=1)
    return int(np.lexsort((totals, impassable))[-1])


# ---------------------------------------------------------------- loading


def load_elevation() -> np.ndarray:
    return np.load(config.ELEVATION_PATH).astype(float)


def load_road_features() -> list[dict[str, Any]]:
    return json.loads(config.ROADS_PATH.read_text(encoding="utf-8"))["features"]
