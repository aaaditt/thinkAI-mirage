import numpy as np
import pytest

from app import config
from app.sky import HistoricalRainSource, gaussian_blur, story_zero_hour


def storm(hours: int = 12, shape: tuple[int, int] = (30, 40)) -> np.ndarray:
    """A rain blob that sits in one corner of the grid for every hour."""
    rows, cols = np.indices(shape)
    blob = 20.0 * np.exp(-((rows - 8) ** 2 + (cols - 10) ** 2) / 40.0)
    return np.repeat(blob[None], hours, axis=0)


def test_blur_keeps_shape_and_total_of_a_flat_field():
    flat = np.full((20, 25), 3.0)
    blurred = gaussian_blur(flat, 2.0)
    assert blurred.shape == flat.shape
    assert np.allclose(blurred, 3.0)


def test_truth_applies_rain_scale():
    source = HistoricalRainSource(storm(), scale=1.5)
    assert np.allclose(source.truth(3), storm()[3] * 1.5)


def test_forecast_has_grid_shape_and_is_never_negative():
    source = HistoricalRainSource(storm())
    for lead in range(1, config.FORECAST_LEADS + 1):
        forecast = source.forecast(2, lead)
        assert forecast.shape == (30, 40)
        assert forecast.min() >= 0.0


def test_forecast_is_identical_on_replay_and_independent_of_call_order():
    first = HistoricalRainSource(storm())
    a = first.forecast(2, 3)
    second = HistoricalRainSource(storm())
    second.forecast(5, 6)  # a different request first must not change the result
    assert np.array_equal(a, second.forecast(2, 3))


def test_forecast_error_grows_with_lead_time():
    source = HistoricalRainSource(storm())
    errors = [
        np.abs(source.forecast(0, lead) - source.truth(lead)).mean()
        for lead in range(1, config.FORECAST_LEADS + 1)
    ]
    assert errors[-1] > errors[0]
    assert errors[0] > 0.0  # even the 1 h forecast is not the truth


def test_forecast_beyond_the_replay_window_is_zero():
    source = HistoricalRainSource(storm(hours=12))
    assert not source.forecast(10, 2).any()


def test_forecast_rejects_bad_lead():
    source = HistoricalRainSource(storm())
    with pytest.raises(ValueError):
        source.forecast(0, 0)
    with pytest.raises(ValueError):
        source.forecast(0, config.FORECAST_LEADS + 1)


def test_story_zero_is_the_wettest_hour_that_leaves_room_for_the_timeline():
    rain = np.zeros((24, 4, 4))
    rain[2] = 50.0  # the wettest hour overall, but too early for a T-6 h lead-in
    rain[16] = 20.0
    rain[23] = 30.0  # too late for a T+2 h tail
    assert story_zero_hour(HistoricalRainSource(rain)) == 16
