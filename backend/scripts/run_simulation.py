"""Run the 24-hour flood simulation on the recorded rain and report on it.

Run from backend/:  python -m scripts.run_simulation
"""

from __future__ import annotations

import sys

import numpy as np

from app import config
from app.config import GRID
from app.ground import (
    build_segment_index,
    build_terrain,
    format_depth,
    load_elevation,
    load_road_features,
    risk_class,
    segment_depths,
    simulate,
)
from app.sensors import SimulatedDepthSensors, place_sensors
from app.sky import load_rain_source, story_zero_hour
from scripts.preview_data import save_map


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")  # road names can be Arabic
    features = load_road_features()
    raw_elevation = load_elevation()
    terrain = build_terrain(raw_elevation, features, GRID)
    source = load_rain_source()
    rain = np.array([source.truth(h) for h in range(config.HOURS)])
    land = ~terrain.open_water
    cells = GRID.rows * GRID.cols

    depths, balances = simulate(rain, terrain)
    index = build_segment_index(features, GRID)
    by_segment = np.array([segment_depths(d, index, terrain.dip_cm) for d in depths])
    classes = risk_class(by_segment)
    peak = story_zero_hour(source)

    lowered = int((terrain.elevation_m != raw_elevation).sum())
    print(f"RAIN_SCALE={config.RAIN_SCALE}  drainage={config.DRAINAGE_CM_PER_HOUR} cm/h  "
          f"land cells={int(land.sum())} of {cells}  "
          f"underpass cells lowered {config.UNDERPASS_DEPTH_M} m: {lowered}")
    print("\nWater balance per hour (mm averaged over the whole grid)")
    print("hour  rain  drained  to_water  stored  | land cells: max_cm  >10cm  >30cm")
    for hour, (b, d) in enumerate(zip(balances, depths)):
        print(f"{hour:02d}    {b.rain_in / cells * 10:5.1f}  {b.drained / cells * 10:6.1f}  "
              f"{b.to_open_water / cells * 10:7.1f}  {b.stored_after / cells * 10:6.1f}  |  "
              f"{d.max():8.0f}  {int((d >= 10).sum()):5d}  {int((d > 30).sum()):5d}")
    print(f"largest balance error: {max(abs(b.error) for b in balances):.2e} cm")

    print(f"\nStory T-0 (hour of heaviest recorded rain): {peak:02d}:00")
    print("\nRoad segments per risk class, per hour")
    print("hour  clear  caution  impassable")
    for hour in range(config.HOURS):
        counts = np.bincount(classes[hour], minlength=3)
        mark = "  <- T-0" if hour == peak else ""
        print(f"{hour:02d}    {counts[0]:5d}  {counts[1]:7d}  {counts[2]:10d}{mark}")

    print(f"\n10 worst road segments at {peak:02d}:00")
    for rank, seg in enumerate(np.argsort(by_segment[peak])[::-1][:10], start=1):
        props = features[seg]["properties"]
        lon, lat = features[seg]["geometry"]["coordinates"][0]
        tag = " [underpass]" if props["underpass"] else ""
        print(f"{rank:2d}. {format_depth(by_segment[peak, seg]):>11}  {props['name'] or '(unnamed)'}"
              f" ({props['highway']}){tag} near {lat:.3f},{lon:.3f}")

    underpass = np.array([f["properties"]["underpass"] for f in features])
    print(f"\nunderpasses at T-0: {np.bincount(classes[peak][underpass], minlength=3)} "
          f"(clear, caution, impassable) of {int(underpass.sum())}")
    sizes = np.diff(np.append(index.starts, index.cells.size))
    print(f"cells per segment: median {np.median(sizes):.0f}, 95th pct "
          f"{np.percentile(sizes, 95):.0f}, max {sizes.max()}")

    sensors = place_sensors(features, GRID, terrain, np.random.default_rng(config.SEED))
    readings = SimulatedDepthSensors(depths, sensors).read(peak)
    wet = sum(r.depth_cm > config.IMPASSABLE_DEPTH_CM for r in readings)
    print(f"sensors: {len(sensors)} placed, {sum(s.at_underpass for s in sensors)} at "
          f"underpasses; {wet} read above {config.IMPASSABLE_DEPTH_CM:.0f} cm at T-0")

    print("\nForecast error vs recorded rain, issued at T-6 (mean absolute, mm)")
    issue = max(peak - 6, 0)
    for lead in range(1, config.FORECAST_LEADS + 1):
        error = np.abs(source.forecast(issue, lead) - source.truth(issue + lead)).mean()
        print(f"  +{lead} h: {error:.2f} (recorded mean {source.truth(issue + lead).mean():.1f})")

    top = float(np.percentile(depths[peak][land], 99.5))
    for label, hour in (("T-6h", peak - 6), ("T-2h", peak - 2), ("T-0", peak)):
        shown = np.where(land, np.clip(depths[hour], 0, top), np.nan)
        save_map(shown, f"Modelled flood depth at {label} ({hour:02d}:00 GST), simplified model",
                 "cm (scale clipped)", "viridis",
                 f"flood_{label.replace('-', 'minus_')}.png", [])


if __name__ == "__main__":
    main()
