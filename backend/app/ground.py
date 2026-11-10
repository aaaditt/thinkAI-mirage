"""Ground engine: a simplified flood surrogate. This is NOT a hydraulic model.

Each hour: add rain, let water run to the lowest neighbouring cell a few times,
remove a fixed drainage amount, never go below zero.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from typing import Any

import numpy as np

from app import config
from app.config import Grid

NEIGHBOUR_OFFSETS = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


@dataclass(frozen=True)
class Terrain:
    """Ground heights the model routes on, and which cells are open water."""

    elevation_m: np.ndarray  # includes the assumed underpass dips
    open_water: np.ndarray  # sea, creek, lagoons: taken from the unmodified elevation
    dip_cm: np.ndarray  # how far each cell was lowered for an underpass (0 elsewhere)


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
    terrain: Terrain,
    drainage_cm: np.ndarray | float = config.DRAINAGE_CM_PER_HOUR,
    substeps: int = config.ROUTING_SUBSTEPS,
    fraction: float = config.FLOW_FRACTION,
) -> tuple[np.ndarray, WaterBalance]:
    """Advance the flood state by one hour. Returns (new depth in cm, balance)."""
    open_water = terrain.open_water
    stored_before = float(depth_cm.sum())
    rain_cm = rain_mm / 10.0
    depth = depth_cm + rain_cm

    to_open_water = 0.0
    for _ in range(substeps):
        depth = route_once(depth, terrain.elevation_m, fraction)
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


def simulate(rain_mm: np.ndarray, terrain: Terrain) -> tuple[np.ndarray, list[WaterBalance]]:
    """Run every hour of `rain_mm` (hours, rows, cols) from a dry start.

    Returns depth (cm) at the end of each hour, and the hourly water balance.
    """
    depth = np.zeros(terrain.elevation_m.shape)
    depths, balances = [], []
    for hour_rain in rain_mm:
        depth, balance = step(depth, hour_rain, terrain)
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
    underpass: np.ndarray  # per segment: True if it is an underpass
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
        underpass=np.array([f["properties"]["underpass"] for f in features], dtype=bool),
        count=len(features),
    )


def deepest_cell(depth_cm: np.ndarray, index: SegmentIndex) -> np.ndarray:
    out = np.zeros(index.count)
    out[index.mapped] = np.maximum.reduceat(depth_cm.ravel()[index.cells], index.starts)
    return out


def segment_depths(depth_cm: np.ndarray, index: SegmentIndex, dip_cm: np.ndarray) -> np.ndarray:
    """Depth per road segment = deepest cell it crosses.

    An underpass sits at the bottom of its dip, so it sees the full depth. A
    surface road in the same cell floods only once the dip has filled. Bridges
    are always 0: we assume the deck stays above the water.
    """
    in_dip = deepest_cell(depth_cm, index)
    at_surface = deepest_cell(np.clip(depth_cm - dip_cm, 0.0, None), index)
    out = np.where(index.underpass, in_dip, at_surface)
    out[index.bridge] = 0.0
    return out


def risk_class(depth_cm: np.ndarray) -> np.ndarray:
    """0 = clear, 1 = caution, 2 = impassable."""
    return (
        (depth_cm >= config.CAUTION_DEPTH_CM).astype(int)
        + (depth_cm > config.IMPASSABLE_DEPTH_CM).astype(int)
    )


def format_depth(depth_cm: float) -> str:
    """Depth for display. Very deep values are artefacts of the coarse terrain,
    so they are reported as a floor, not a number."""
    if depth_cm > config.DISPLAY_DEPTH_CAP_CM:
        return f"over {config.DISPLAY_DEPTH_CAP_CM:.0f} cm"
    return f"{depth_cm:.0f} cm"


# ---------------------------------------------------------------- loading


def underpass_cells(features: list[dict[str, Any]], grid: Grid) -> np.ndarray:
    """Flat indices of the cells crossed by underpass (non-bridge) segments."""
    cells = [
        line_cells(f["geometry"]["coordinates"], grid)
        for f in features
        if f["properties"]["underpass"] and not f["properties"]["bridge"]
    ]
    return np.unique(np.concatenate(cells)) if cells else np.array([], dtype=int)


def build_terrain(
    raw_elevation_m: np.ndarray, features: list[dict[str, Any]], grid: Grid
) -> Terrain:
    """Terrain with each land underpass cell lowered by an ASSUMED depth.

    The elevation data shows the road surface around an underpass, not its dip.
    """
    open_water = raw_elevation_m <= config.WATER_LEVEL_M
    cells = underpass_cells(features, grid)
    cells = cells[~open_water.ravel()[cells]]
    dip_m = np.zeros(raw_elevation_m.shape)
    dip_m.ravel()[cells] = config.UNDERPASS_DEPTH_M
    return Terrain(
        elevation_m=raw_elevation_m - dip_m, open_water=open_water, dip_cm=dip_m * 100.0
    )


def load_elevation() -> np.ndarray:
    return np.load(config.ELEVATION_PATH).astype(float)


def split_line(coords: list[list[float]], max_m: float) -> list[list[list[float]]]:
    """Cut a (lon, lat) line into equal pieces no longer than `max_m` metres."""
    points = np.asarray(coords, dtype=float)
    scale_x = config.METRES_PER_DEG_LAT * math.cos(math.radians(points[0, 1]))
    along = np.concatenate([[0.0], np.cumsum(np.hypot(
        np.diff(points[:, 0]) * scale_x, np.diff(points[:, 1]) * config.METRES_PER_DEG_LAT))])
    pieces = max(1, math.ceil(along[-1] / max_m))
    if pieces == 1:
        return [coords]
    cuts = np.linspace(0.0, along[-1], pieces + 1)
    out = []
    for start, end in zip(cuts[:-1], cuts[1:]):
        inner = along[(along > start) & (along < end)]
        stops = np.concatenate([[start], inner, [end]])
        lons = np.interp(stops, along, points[:, 0])
        lats = np.interp(stops, along, points[:, 1])
        out.append([[round(float(x), 5), round(float(y), 5)] for x, y in zip(lons, lats)])
    return out


def split_long_features(features: list[dict[str, Any]], max_m: float) -> list[dict[str, Any]]:
    """Road segments for the model: each OSM way cut into pieces of at most `max_m`."""
    return [
        {**feature, "geometry": {"type": "LineString", "coordinates": piece}}
        for feature in features
        for piece in split_line(feature["geometry"]["coordinates"], max_m)
    ]


def load_road_features() -> list[dict[str, Any]]:
    ways = json.loads(config.ROADS_PATH.read_text(encoding="utf-8"))["features"]
    return split_long_features(ways, config.MAX_SEGMENT_M)
