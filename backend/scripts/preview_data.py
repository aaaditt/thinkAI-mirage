"""Save sanity-check PNGs of the cached rainfall and elevation to data/previews/.

Run from backend/:  python -m scripts.preview_data
"""

from __future__ import annotations

import json

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.axes import Axes
from matplotlib.collections import LineCollection

from app import config

PREVIEW_DIR = config.DATA_DIR / "previews"
EXTENT = (config.LON_MIN, config.LON_MAX, config.LAT_MIN, config.LAT_MAX)


def draw_context(ax: Axes, road_lines: list[np.ndarray]) -> None:
    """Major roads and district labels, so the picture can be read as Dubai."""
    ax.add_collection(LineCollection(road_lines, colors="white", linewidths=0.3, alpha=0.5))
    for name, (lat, lon) in config.DISTRICTS.items():
        ax.plot(lon, lat, "o", color="#F2A93B", markersize=4)
        ax.annotate(name, (lon, lat), color="#F2A93B", fontsize=8,
                    xytext=(4, 4), textcoords="offset points")
    ax.set_xlim(EXTENT[0], EXTENT[1])
    ax.set_ylim(EXTENT[2], EXTENT[3])
    ax.set_xlabel("longitude")
    ax.set_ylabel("latitude")


def save_map(data: np.ndarray, title: str, label: str, cmap: str, filename: str,
             road_lines: list[np.ndarray]) -> None:
    fig, ax = plt.subplots(figsize=(9, 7), facecolor="#0B1220")
    image = ax.imshow(data, origin="lower", extent=EXTENT, cmap=cmap, aspect="auto")
    draw_context(ax, road_lines)
    ax.set_title(title, color="#E6ECF3")
    ax.tick_params(colors="#E6ECF3")
    ax.xaxis.label.set_color("#E6ECF3")
    ax.yaxis.label.set_color("#E6ECF3")
    bar = fig.colorbar(image, ax=ax)
    bar.set_label(label, color="#E6ECF3")
    bar.ax.tick_params(colors="#E6ECF3")
    fig.savefig(PREVIEW_DIR / filename, dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"saved {PREVIEW_DIR / filename}")


def main() -> None:
    PREVIEW_DIR.mkdir(exist_ok=True)
    rain = np.load(config.RAIN_TRUTH_PATH)
    elevation = np.load(config.ELEVATION_PATH)
    roads = json.loads(config.ROADS_PATH.read_text(encoding="utf-8"))["features"]
    major = [np.asarray(f["geometry"]["coordinates"]) for f in roads
             if f["properties"]["highway"] in ("motorway", "trunk", "primary")]

    peak = int(rain.mean(axis=(1, 2)).argmax())
    save_map(rain[peak], f"Recorded rainfall, {config.REPLAY_DATE} hour ending {peak:02d}:00 GST",
             "mm in the hour", "Blues", "rain_peak_hour.png", major)
    save_map(rain.sum(axis=0), f"Recorded rainfall, {config.REPLAY_DATE} 24 h total",
             "mm", "Blues", "rain_total.png", major)
    # Clip the colour scale so a few high cells do not wash out the flat city.
    top = float(np.percentile(elevation, 98))
    save_map(np.clip(elevation, None, top), "Elevation (colour scale clipped at 98th percentile)",
             "m above sea level", "terrain", "elevation.png", major)


if __name__ == "__main__":
    main()
