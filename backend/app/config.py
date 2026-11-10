"""Static configuration: study area, grid, replay window, data paths."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "data"

RAIN_POINTS_PATH = DATA_DIR / "rain_points.json"
RAIN_TRUTH_PATH = DATA_DIR / "rain_truth.npy"
ELEVATION_PATH = DATA_DIR / "elevation.npy"
ELEVATION_PARTIAL_PATH = DATA_DIR / "elevation_partial.npy"
ROADS_PATH = DATA_DIR / "roads.geojson"
TIMELINE_PATH = DATA_DIR / "timeline.npz"

DISCLAIMER = "Prototype — simulated sensors, simplified flood model"
CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
RAIN_DOWNSAMPLE = 4  # rain grids are sent to the browser as 4x4-cell block means

# Dubai urban core.
LAT_MIN, LAT_MAX = 25.03, 25.30
LON_MIN, LON_MAX = 55.10, 55.42

CELL_SIZE_M = float(os.environ.get("CELL_SIZE_M", "200"))
# Elevation is fetched for every Nth cell (N * CELL_SIZE_M spacing) and interpolated,
# because the elevation API's quota counts each coordinate.
ELEVATION_SAMPLE_STRIDE = 2
RAIN_SCALE = float(os.environ.get("RAIN_SCALE", "1.0"))

# Replay window: 16 April 2024, 00:00-23:00 Gulf Standard Time (UTC+4), hourly.
REPLAY_DATE = "2024-04-16"
TIMEZONE = "Asia/Dubai"
HOURS = 24
# The story timeline runs from T-6 h to T+2 h around the computed T-0.
STORY_HOURS_BEFORE = 6
STORY_HOURS_AFTER = 2

SEED = 20240416

# --- Sky: simulated forecast = truth, blurred and perturbed more as lead time grows.
FORECAST_LEADS = 6
FORECAST_BLUR_CELLS_PER_LEAD = 1.5  # Gaussian sigma, in cells, per hour of lead
FORECAST_NOISE_PER_LEAD = 0.08  # relative error (log-normal sigma) per hour of lead
FORECAST_NOISE_CORRELATION_CELLS = 10.0  # error patches are about 2 km wide

# --- Ground: simplified surrogate. These are assumptions, not calibrated values.
WATER_LEVEL_M = 0.0  # cells at or below this are open water (sea, creek, lagoons)
UNDERPASS_DEPTH_M = 3.0  # assumed dip: the elevation data cannot see underpasses
DRAINAGE_CM_PER_HOUR = 0.5  # drains + infiltration removed from every land cell
FLOW_FRACTION = 0.5  # share of a cell's water that may move per sub-step
ROUTING_SUBSTEPS = 6  # water travels at most one cell (200 m) per sub-step
MAX_SEGMENT_M = 400.0  # longer OSM ways are cut up, so one wet cell cannot flag km of road
CAUTION_DEPTH_CM = 10.0  # below: clear
IMPASSABLE_DEPTH_CM = 30.0  # above: impassable
DISPLAY_DEPTH_CAP_CM = 100.0  # deeper values are shown as "over 100 cm"
SENSOR_BLEND_WEIGHT = 0.7  # how far a model cell is pulled toward a sensor reading

# --- Simulated depth sensors.
SENSOR_COUNT = 60
SENSOR_UNDERPASS_COUNT = 20  # sensors placed at underpasses first, rest on other roads
SENSOR_RELATIVE_NOISE = 0.10
SENSOR_ABSOLUTE_NOISE_CM = 1.0

# OSM highway classes kept as road segments ("_link" ramps are included too).
ROAD_CLASSES = ("motorway", "trunk", "primary", "secondary", "tertiary")

# Approximate centres of the focus districts: name -> (lat, lon).
DISTRICTS: dict[str, tuple[float, float]] = {
    "Al Barsha": (25.11, 55.20),
    "Al Quoz": (25.14, 55.24),
    "Business Bay": (25.185, 55.27),
}

METRES_PER_DEG_LAT = 111_320.0


@dataclass(frozen=True)
class Grid:
    """Regular lat/lon grid. Row 0 is the southern edge, column 0 the western."""

    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    rows: int
    cols: int

    @property
    def shape(self) -> tuple[int, int]:
        return (self.rows, self.cols)

    def lats(self) -> np.ndarray:
        """Cell-centre latitudes, south to north."""
        step = (self.lat_max - self.lat_min) / self.rows
        return self.lat_min + step * (np.arange(self.rows) + 0.5)

    def lons(self) -> np.ndarray:
        """Cell-centre longitudes, west to east."""
        step = (self.lon_max - self.lon_min) / self.cols
        return self.lon_min + step * (np.arange(self.cols) + 0.5)


def build_grid(cell_size_m: float = CELL_SIZE_M) -> Grid:
    """Grid over the bounding box with cells of roughly `cell_size_m` metres."""
    mid_lat = math.radians((LAT_MIN + LAT_MAX) / 2)
    height_m = (LAT_MAX - LAT_MIN) * METRES_PER_DEG_LAT
    width_m = (LON_MAX - LON_MIN) * METRES_PER_DEG_LAT * math.cos(mid_lat)
    return Grid(
        lat_min=LAT_MIN,
        lat_max=LAT_MAX,
        lon_min=LON_MIN,
        lon_max=LON_MAX,
        rows=round(height_m / cell_size_m),
        cols=round(width_m / cell_size_m),
    )


GRID = build_grid()

# --- City: mock resources and planning rules. All of this is invented for the demo.
PUMP_COUNT = 12
TANKER_COUNT = 6
# Mock depots: name -> (lat, lon, pumps, tankers).
DEPOTS: dict[str, tuple[float, float, int, int]] = {
    "Al Quoz depot (mock)": (25.135, 55.235, 6, 3),
    "Ras Al Khor depot (mock)": (25.180, 55.350, 6, 3),
}
# Assumed: one pump moves about 1,000 m3/h, which is 2.5 cm/h over one 200 m cell.
PUMP_DRAINAGE_CM_PER_HOUR = 2.5
PLAN_TOP_UNDERPASSES = 10
PLAN_TOP_ROADS = 5
MAX_CLOSURES_PER_PLAN = 4
MAX_PUMPS_PER_PLAN = 3
PUMP_MIN_LEAD_HOURS = 2  # a pump is only staged where there is time to get it there
DISTRICT_RADIUS_KM = 2.5
ALERT_MIN_NEW_SEGMENTS = 5  # a district alert needs this many more impassable segments
ALERT_MIN_LEAD_HOURS = 1
ALERT_SPACING_HOURS = 3
ALERT_MAX_CHARS = 160
# `or` so that an empty value copied from .env.example still gets the default.
AZURE_OPENAI_API_VERSION = os.environ.get("AZURE_OPENAI_API_VERSION") or "2024-10-21"
