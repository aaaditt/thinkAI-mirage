import numpy as np

from app import config
from app.replay import block_mean


def test_block_mean_handles_a_ragged_edge():
    field = np.arange(30.0).reshape(5, 6)
    small = block_mean(field, 4)
    assert small.shape == (2, 2)
    assert small[0, 0] == field[:4, :4].mean()
    assert small[1, 1] == field[4:, 4:].mean()


def test_block_mean_preserves_a_uniform_field_on_stacked_grids():
    small = block_mean(np.full((3, 2, 10, 10), 7.0), 4)
    assert small.shape == (3, 2, 3, 3)
    assert np.allclose(small, 7.0)


def test_timeline_shapes(small_world):
    scenario, timeline = small_world.scenario, small_world.timeline
    n, s = len(scenario.features), len(scenario.sensors)
    leads = config.FORECAST_LEADS
    assert timeline.rain_small.shape == (config.HOURS, 3, 3)
    assert timeline.forecast_small.shape == (config.HOURS, leads, 3, 3)
    assert timeline.segment_model_cm.shape == (config.HOURS, n)
    assert timeline.segment_cm.shape == (config.HOURS, n)
    assert timeline.segment_forecast_cm.shape == (config.HOURS, leads, n)
    assert timeline.sensor_cm.shape == (config.HOURS, s)


def test_timeline_has_no_negative_or_missing_values(small_world):
    for name, array in vars(small_world.timeline).items():
        assert np.isfinite(array).all(), name
        assert array.min() >= 0.0, name


def test_sensor_correction_changes_the_model_estimate(small_world):
    timeline = small_world.timeline
    assert not np.array_equal(timeline.segment_model_cm, timeline.segment_cm)


def test_bridges_stay_dry_through_the_whole_timeline(small_world):
    bridge = [f["properties"]["bridge"] for f in small_world.scenario.features]
    assert not small_world.timeline.segment_cm[:, bridge].any()
    assert not small_world.timeline.segment_forecast_cm[:, :, bridge].any()


def test_story_zero_is_the_wet_hour(small_world):
    assert small_world.scenario.zero_hour == 14
