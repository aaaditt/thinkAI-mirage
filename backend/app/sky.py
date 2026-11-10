"""Sky engine: recorded rainfall and a simulated nowcast derived from it.

The "forecast" is NOT a weather model. It is the historical record for the target
hour, blurred and perturbed with seeded noise that grows with lead time.
"""

from __future__ import annotations

from typing import Protocol

import numpy as np

from app import config


class RainSource(Protocol):
    """Where rainfall comes from. A real radar feed could implement this later."""

    def truth(self, hour: int) -> np.ndarray:
        """Rain (mm) that fell in `hour`, shape (rows, cols)."""
        ...

    def forecast(self, issue_hour: int, lead: int) -> np.ndarray:
        """Rain (mm) predicted at `issue_hour` for `issue_hour + lead`."""
        ...


def gaussian_blur(field: np.ndarray, sigma: float) -> np.ndarray:
    """Separable Gaussian blur with edge padding; sigma in cells."""
    if sigma <= 0:
        return field.astype(float)
    radius = int(3 * sigma) + 1
    offsets = np.arange(-radius, radius + 1)
    kernel = np.exp(-(offsets**2) / (2 * sigma**2))
    kernel /= kernel.sum()
    padded = np.pad(field.astype(float), radius, mode="edge")
    rows_done = np.apply_along_axis(np.convolve, 0, padded, kernel, "valid")
    return np.apply_along_axis(np.convolve, 1, rows_done, kernel, "valid")


def error_field(shape: tuple[int, int], sigma: float, rng: np.random.Generator) -> np.ndarray:
    """Spatially correlated multiplicative error with mean 1 (log-normal)."""
    smooth = gaussian_blur(rng.standard_normal(shape), config.FORECAST_NOISE_CORRELATION_CELLS)
    unit = (smooth - smooth.mean()) / smooth.std()
    return np.exp(sigma * unit - 0.5 * sigma**2)


class HistoricalRainSource:
    """Simulated RainSource built from the cached historical record."""

    def __init__(self, rain_mm: np.ndarray, scale: float = 1.0, seed: int = config.SEED):
        self._rain = rain_mm.astype(float) * scale
        self._seed = seed

    @property
    def hours(self) -> int:
        return self._rain.shape[0]

    def truth(self, hour: int) -> np.ndarray:
        return self._rain[hour]

    def forecast(self, issue_hour: int, lead: int) -> np.ndarray:
        if not 1 <= lead <= config.FORECAST_LEADS:
            raise ValueError(f"lead must be 1..{config.FORECAST_LEADS}, got {lead}")
        target = issue_hour + lead
        if target >= self.hours:  # beyond the replay window: no data, so no rain
            return np.zeros(self._rain.shape[1:])
        rng = np.random.default_rng([self._seed, issue_hour, lead])
        blurred = gaussian_blur(self._rain[target], config.FORECAST_BLUR_CELLS_PER_LEAD * lead)
        return blurred * error_field(blurred.shape, config.FORECAST_NOISE_PER_LEAD * lead, rng)


def story_zero_hour(source: HistoricalRainSource) -> int:
    """Story "T-0": the hour with the heaviest recorded rain, averaged over the area.

    Computed from the record, never hard-coded. Restricted to hours that leave
    room for the T-6 h lead-in and the T+2 h tail inside the replay window.
    """
    first, last = config.STORY_HOURS_BEFORE, source.hours - 1 - config.STORY_HOURS_AFTER
    means = [float(source.truth(hour).mean()) for hour in range(first, last + 1)]
    return first + int(np.argmax(means))


def load_rain_source() -> HistoricalRainSource:
    """The cached record for the replay day, with RAIN_SCALE applied."""
    return HistoricalRainSource(np.load(config.RAIN_TRUTH_PATH), scale=config.RAIN_SCALE)
