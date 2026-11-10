"""One-off fetchers: rainfall, elevation and roads -> data/.

Run from backend/:  python -m app.data_fetch [rain|elevation|roads|all|report]

Every fetch is cached in data/, so the demo itself never needs the network.
"""

from __future__ import annotations

import json
import math
import sys
import time
from collections.abc import Iterator, Sequence
from typing import Any

import httpx
import numpy as np

from app import config
from app.config import GRID, Grid

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
ELEVATION_URL = "https://api.open-meteo.com/v1/elevation"
OVERPASS_URL = "https://overpass-api.de/api/interpreter"
USER_AGENT = "mirage-prototype/0.1"

# Open-Meteo rejects more than 100 coordinates per request (verified: HTTP 400).
MAX_COORDS_PER_REQUEST = 100
REQUEST_PAUSE_S = 0.3
RATE_LIMIT_WAIT_S = 65.0
MAX_RETRIES = 5

# The archive snaps each request to its nearest model cell (about 0.07 deg apart),
# so we over-sample a padded lattice and keep the distinct cells that come back.
RAIN_LATTICE_STEP_DEG = 0.035
RAIN_LATTICE_PAD_DEG = 0.08

SIMPLIFY_TOLERANCE_M = 5.0

Coord = tuple[float, float]  # (lon, lat), GeoJSON order


# ---------------------------------------------------------------- helpers


def chunked(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def request_json(client: httpx.Client, method: str, url: str, **kwargs: Any) -> Any:
    """HTTP request returning JSON; waits and retries on rate limits and 5xx."""
    for attempt in range(1, MAX_RETRIES + 1):
        response = client.request(method, url, **kwargs)
        if response.status_code == 429 or response.status_code >= 500:
            print(f"  HTTP {response.status_code}, waiting {RATE_LIMIT_WAIT_S:.0f}s "
                  f"(attempt {attempt}/{MAX_RETRIES})")
            time.sleep(RATE_LIMIT_WAIT_S)
            continue
        response.raise_for_status()
        return response.json()
    raise RuntimeError(f"{url} still failing after {MAX_RETRIES} attempts")


def new_client() -> httpx.Client:
    return httpx.Client(timeout=240.0, headers={"User-Agent": USER_AGENT})


# ---------------------------------------------------------------- rainfall


def rain_lattice() -> list[tuple[float, float]]:
    """(lat, lon) request points covering the padded bounding box."""
    pad, step = RAIN_LATTICE_PAD_DEG, RAIN_LATTICE_STEP_DEG
    lats = np.arange(config.LAT_MIN - pad, config.LAT_MAX + pad + step, step)
    lons = np.arange(config.LON_MIN - pad, config.LON_MAX + pad + step, step)
    return [(round(float(a), 4), round(float(o), 4)) for a in lats for o in lons]


def fetch_rain_points(client: httpx.Client) -> list[dict[str, Any]]:
    """Hourly precipitation (mm) for each distinct archive cell near the bbox."""
    cells: dict[tuple[float, float], dict[str, Any]] = {}
    for chunk in chunked(rain_lattice(), MAX_COORDS_PER_REQUEST):
        data = request_json(client, "GET", ARCHIVE_URL, params={
            "latitude": ",".join(str(lat) for lat, _ in chunk),
            "longitude": ",".join(str(lon) for _, lon in chunk),
            "start_date": config.REPLAY_DATE,
            "end_date": config.REPLAY_DATE,
            "hourly": "precipitation",
            "timezone": config.TIMEZONE,
        })
        for item in data if isinstance(data, list) else [data]:
            precip = item["hourly"]["precipitation"]
            if len(precip) != config.HOURS or any(v is None for v in precip):
                raise ValueError(f"unexpected precipitation series: {precip}")
            cells[(item["latitude"], item["longitude"])] = {
                "lat": item["latitude"],
                "lon": item["longitude"],
                "precipitation_mm": precip,
            }
        time.sleep(REQUEST_PAUSE_S)
    return list(cells.values())


def idw_weights(
    src_lats: np.ndarray, src_lons: np.ndarray, grid: Grid, power: float = 2.0
) -> np.ndarray:
    """Inverse-distance weights, shape (rows*cols, n_sources); each row sums to 1."""
    lat_grid, lon_grid = np.meshgrid(grid.lats(), grid.lons(), indexing="ij")
    lon_scale = math.cos(math.radians((grid.lat_min + grid.lat_max) / 2))
    dy = lat_grid.reshape(-1, 1) - src_lats.reshape(1, -1)
    dx = (lon_grid.reshape(-1, 1) - src_lons.reshape(1, -1)) * lon_scale
    weights = 1.0 / (np.hypot(dx, dy) ** power + 1e-12)
    return weights / weights.sum(axis=1, keepdims=True)


def interpolate_rain(points: list[dict[str, Any]], grid: Grid) -> np.ndarray:
    """Scattered hourly series -> array (hours, rows, cols) in mm, float32."""
    src_lats = np.array([p["lat"] for p in points])
    src_lons = np.array([p["lon"] for p in points])
    series = np.array([p["precipitation_mm"] for p in points])  # (n_sources, hours)
    gridded = idw_weights(src_lats, src_lons, grid) @ series  # (cells, hours)
    return gridded.T.reshape(series.shape[1], *grid.shape).astype(np.float32)


def fetch_rainfall() -> None:
    with new_client() as client:
        points = fetch_rain_points(client)
    config.RAIN_POINTS_PATH.write_text(json.dumps(points), encoding="utf-8")
    np.save(config.RAIN_TRUTH_PATH, interpolate_rain(points, GRID))
    print(f"rain: {len(points)} distinct archive cells -> {config.RAIN_TRUTH_PATH.name}")


# ---------------------------------------------------------------- elevation


def upsample_bilinear(
    coarse: np.ndarray, rows: np.ndarray, cols: np.ndarray, shape: tuple[int, int]
) -> np.ndarray:
    """Bilinear fill of a `shape` grid from samples at (rows, cols); edges clamp."""
    along_cols = np.array([np.interp(np.arange(shape[1]), cols, line) for line in coarse])
    return np.array(
        [np.interp(np.arange(shape[0]), rows, column) for column in along_cols.T]
    ).T


def fetch_elevation() -> None:
    """Elevation (m) per grid cell; resumes from a partial file.

    Open-Meteo counts every coordinate against its hourly quota, so we sample
    every ELEVATION_SAMPLE_STRIDE-th cell and interpolate the cells in between.
    """
    lat_grid, lon_grid = np.meshgrid(GRID.lats(), GRID.lons(), indexing="ij")
    lats, lons = lat_grid.ravel(), lon_grid.ravel()
    partial = config.ELEVATION_PARTIAL_PATH
    flat = np.load(partial) if partial.exists() else np.full(lats.size, np.nan)
    if flat.size != lats.size:
        raise ValueError(f"{partial.name} does not match the current grid; delete it")

    rows = np.arange(0, GRID.rows, config.ELEVATION_SAMPLE_STRIDE)
    cols = np.arange(0, GRID.cols, config.ELEVATION_SAMPLE_STRIDE)
    lattice = (rows[:, None] * GRID.cols + cols[None, :]).ravel()
    missing = lattice[np.isnan(flat[lattice])]
    print(f"elevation: {missing.size} of {lattice.size} sample points still to fetch")

    batches = list(chunked(missing, MAX_COORDS_PER_REQUEST))
    with new_client() as client:
        for number, index in enumerate(batches, start=1):
            data = request_json(client, "GET", ELEVATION_URL, params={
                "latitude": ",".join(f"{v:.5f}" for v in lats[index]),
                "longitude": ",".join(f"{v:.5f}" for v in lons[index]),
            })
            flat[index] = data["elevation"]
            np.save(partial, flat)  # every batch: quota errors must not lose progress
            if number % 20 == 0:
                print(f"  elevation batch {number}/{len(batches)}")
            time.sleep(REQUEST_PAUSE_S)

    coarse = flat[lattice].reshape(rows.size, cols.size)
    elevation = upsample_bilinear(coarse, rows, cols, GRID.shape)
    np.save(config.ELEVATION_PATH, elevation.astype(np.float32))
    partial.unlink(missing_ok=True)
    print(f"elevation: {rows.size}x{cols.size} samples -> {GRID.rows}x{GRID.cols} cells "
          f"-> {config.ELEVATION_PATH.name}")



# ---------------------------------------------------------------- roads


def overpass_query() -> str:
    classes = "|".join(config.ROAD_CLASSES)
    bbox = f"{config.LAT_MIN},{config.LON_MIN},{config.LAT_MAX},{config.LON_MAX}"
    return (
        "[out:json][timeout:180];"
        f'way["highway"~"^({classes})(_link)?$"]({bbox});'
        "out tags geom;"
    )


def is_underpass(tags: dict[str, str]) -> bool:
    """True where OSM has tunnel=yes or a negative layer."""
    if tags.get("tunnel") == "yes":
        return True
    try:
        return float(tags.get("layer", "0")) < 0
    except ValueError:
        return False


def simplify_line(coords: list[Coord], tolerance_m: float) -> list[Coord]:
    """Douglas-Peucker simplification; endpoints are always kept."""
    if len(coords) < 3:
        return coords
    pts = np.asarray(coords, dtype=float)
    scale_x = config.METRES_PER_DEG_LAT * math.cos(math.radians(pts[0, 1]))
    xy = np.column_stack([pts[:, 0] * scale_x, pts[:, 1] * config.METRES_PER_DEG_LAT])
    keep = np.zeros(len(coords), dtype=bool)
    keep[[0, -1]] = True
    stack = [(0, len(coords) - 1)]
    while stack:
        first, last = stack.pop()
        if last - first < 2:
            continue
        inner = xy[first + 1 : last]
        chord = xy[last] - xy[first]
        length = float(np.hypot(*chord))
        offset = inner - xy[first]
        if length == 0.0:
            dist = np.hypot(offset[:, 0], offset[:, 1])
        else:
            dist = np.abs(chord[0] * offset[:, 1] - chord[1] * offset[:, 0]) / length
        worst = int(np.argmax(dist))
        if dist[worst] > tolerance_m:
            split = first + 1 + worst
            keep[split] = True
            stack += [(first, split), (split, last)]
    return [c for c, k in zip(coords, keep) if k]


def way_to_feature(way: dict[str, Any]) -> dict[str, Any] | None:
    """Overpass way -> GeoJSON LineString feature (None if it has no line)."""
    coords = [(p["lon"], p["lat"]) for p in way.get("geometry", [])]
    if len(coords) < 2:
        return None
    tags = way.get("tags", {})
    line = simplify_line(coords, SIMPLIFY_TOLERANCE_M)
    return {
        "type": "Feature",
        "geometry": {
            "type": "LineString",
            "coordinates": [[round(lon, 5), round(lat, 5)] for lon, lat in line],
        },
        "properties": {
            "id": way["id"],
            "name": tags.get("name:en") or tags.get("name") or "",
            "highway": tags["highway"],
            "underpass": is_underpass(tags),
            "bridge": tags.get("bridge", "no") != "no",
        },
    }


def fetch_roads() -> None:
    with new_client() as client:
        data = request_json(client, "POST", OVERPASS_URL, data={"data": overpass_query()})
    features = [f for f in map(way_to_feature, data["elements"]) if f is not None]
    collection = {
        "type": "FeatureCollection",
        "attribution": "© OpenStreetMap contributors (ODbL)",
        "features": features,
    }
    config.ROADS_PATH.write_text(
        json.dumps(collection, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    print(f"roads: {len(features)} segments -> {config.ROADS_PATH.name}")


# ---------------------------------------------------------------- report


def report() -> None:
    """Print a summary of the cached data."""
    rain = np.load(config.RAIN_TRUTH_PATH)
    elevation = np.load(config.ELEVATION_PATH)
    roads = json.loads(config.ROADS_PATH.read_text(encoding="utf-8"))["features"]
    points = json.loads(config.RAIN_POINTS_PATH.read_text(encoding="utf-8"))
    hourly_mean = rain.mean(axis=(1, 2))
    peak_hour = int(hourly_mean.argmax())
    whole = float(np.mean(elevation == np.round(elevation)))

    print(f"grid shape (rows, cols): {GRID.shape} = {GRID.rows * GRID.cols} cells")
    print(f"rain source cells: {len(points)}")
    print(f"rain 24 h total: area mean {rain.sum(axis=0).mean():.1f} mm, "
          f"wettest cell {rain.sum(axis=0).max():.1f} mm")
    print(f"rain peak hour: {peak_hour:02d}:00 (area mean {hourly_mean[peak_hour]:.1f} mm, "
          f"max cell {rain[peak_hour].max():.1f} mm); max cell any hour {rain.max():.1f} mm")
    print(f"elevation: min {elevation.min():.1f} m, max {elevation.max():.1f} m, "
          f"median {np.median(elevation):.1f} m, whole-metre cells {whole:.0%}")
    print(f"road segments: {len(roads)}, "
          f"underpasses: {sum(f['properties']['underpass'] for f in roads)}, "
          f"bridges: {sum(f['properties']['bridge'] for f in roads)}")
    for path in (config.RAIN_POINTS_PATH, config.RAIN_TRUTH_PATH,
                 config.ELEVATION_PATH, config.ROADS_PATH):
        print(f"  {path.name}: {path.stat().st_size / 1024:.0f} KB")


COMMANDS = {
    "rain": fetch_rainfall,
    "elevation": fetch_elevation,
    "roads": fetch_roads,
    "report": report,
}


def main(argv: list[str]) -> None:
    command = argv[1] if len(argv) > 1 else "all"
    if command != "all" and command not in COMMANDS:
        raise SystemExit(f"usage: python -m app.data_fetch [{'|'.join(COMMANDS)}|all]")
    config.DATA_DIR.mkdir(exist_ok=True)
    for name in COMMANDS if command == "all" else [command]:
        COMMANDS[name]()


if __name__ == "__main__":
    main(sys.argv)
