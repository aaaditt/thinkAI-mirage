import numpy as np

from app import config
from app.config import Grid
from app.ground import (
    blend_toward_sensors,
    build_segment_index,
    line_cells,
    peak_flood_hour,
    risk_class,
    route_once,
    segment_depths,
    simulate,
    step,
)

GRID = Grid(lat_min=25.0, lat_max=25.1, lon_min=55.0, lon_max=55.1, rows=10, cols=10)


def bowl(size: int = 9) -> np.ndarray:
    """Land that slopes down to a low point in the middle, all above sea level."""
    rows, cols = np.indices((size, size))
    return 1.0 + 0.1 * np.hypot(rows - size // 2, cols - size // 2)


def road(coords: list[list[float]], bridge: bool = False) -> dict:
    return {"geometry": {"coordinates": coords}, "properties": {"bridge": bridge}}


# ---------------------------------------------------------------- routing


def test_routing_conserves_water_on_random_terrain():
    rng = np.random.default_rng(0)
    elevation = rng.uniform(1.0, 5.0, (20, 20))
    depth = rng.uniform(0.0, 50.0, (20, 20))
    for _ in range(25):
        routed = route_once(depth, elevation, 0.5)
        assert np.isclose(routed.sum(), depth.sum())
        assert routed.min() >= 0.0
        depth = routed


def test_water_runs_downhill_into_the_bowl():
    depth = np.full((9, 9), 5.0)
    for _ in range(30):
        depth = route_once(depth, bowl(), 0.5)
    assert depth[4, 4] > 5.0
    assert depth[0, 0] < 5.0


def test_a_level_pool_does_not_move():
    elevation = np.full((6, 6), 2.0)
    depth = np.full((6, 6), 12.0)
    assert np.array_equal(route_once(depth, elevation, 0.5), depth)


# ---------------------------------------------------------------- hourly step


def test_water_is_lost_only_through_drainage_when_there_is_no_open_water():
    depth, balance = step(np.zeros((9, 9)), np.full((9, 9), 40.0), bowl(), drainage_cm=0.5)
    assert balance.to_open_water == 0.0
    assert balance.rain_in == 9 * 9 * 4.0
    assert 0.0 < balance.drained <= 9 * 9 * 0.5
    assert np.isclose(depth.sum(), balance.rain_in - balance.drained)
    assert abs(balance.error) < 1e-9


def test_no_rain_never_creates_water():
    depth, balance = step(np.zeros((9, 9)), np.zeros((9, 9)), bowl())
    assert not depth.any()
    assert balance.stored_after == 0.0


def test_depth_never_goes_negative_when_drainage_exceeds_water():
    depth, _ = step(np.full((9, 9), 0.1), np.zeros((9, 9)), bowl(), drainage_cm=5.0)
    assert depth.min() == 0.0


def test_open_water_cells_stay_dry_and_their_loss_is_counted():
    elevation = bowl()
    elevation[4, 4] = 0.0  # a lagoon at the low point
    depth, balance = step(np.zeros((9, 9)), np.full((9, 9), 40.0), elevation)
    assert depth[4, 4] == 0.0
    assert balance.to_open_water > 0.0
    assert abs(balance.error) < 1e-9


def test_simulation_balance_closes_every_hour():
    rain = np.random.default_rng(1).uniform(0.0, 30.0, (6, 9, 9))
    elevation = bowl()
    elevation[0, 0] = 0.0
    depths, balances = simulate(rain, elevation)
    assert depths.shape == (6, 9, 9)
    assert all(abs(b.error) < 1e-6 for b in balances)
    assert all(a.stored_after == b.stored_before for a, b in zip(balances, balances[1:]))


def test_extra_local_drainage_lowers_depth_there():
    rain = np.full((9, 9), 40.0)
    base, _ = step(np.zeros((9, 9)), rain, bowl(), drainage_cm=0.5)
    boosted_drainage = np.full((9, 9), 0.5)
    boosted_drainage[4, 4] = 10.0
    boosted, _ = step(np.zeros((9, 9)), rain, bowl(), drainage_cm=boosted_drainage)
    assert boosted[4, 4] < base[4, 4]


# ---------------------------------------------------------------- correction


def test_blend_pulls_only_sensor_cells_toward_the_reading():
    depth = np.full((4, 4), 10.0)
    corrected = blend_toward_sensors(
        depth, np.array([1]), np.array([2]), np.array([30.0]), weight=0.5
    )
    assert corrected[1, 2] == 20.0
    corrected[1, 2] = 10.0
    assert np.array_equal(corrected, depth)


# ---------------------------------------------------------------- roads


def test_line_cells_follow_a_west_east_line_and_ignore_points_off_grid():
    cells = line_cells([[54.99, 25.005], [55.035, 25.005]], GRID)
    assert list(cells) == [0, 1, 2, 3]


def test_segment_depth_is_deepest_cell_and_bridges_are_zero():
    depth = np.zeros(GRID.shape)
    depth[0, 2] = 45.0
    line = [[55.005, 25.005], [55.035, 25.005]]
    outside = [[60.0, 30.0], [60.1, 30.0]]
    index = build_segment_index([road(line), road(line, bridge=True), road(outside)], GRID)
    assert list(segment_depths(depth, index)) == [45.0, 0.0, 0.0]


def test_risk_classes_use_configured_thresholds():
    depths = np.array([0.0, 9.9, config.CAUTION_DEPTH_CM, config.IMPASSABLE_DEPTH_CM, 30.1])
    assert list(risk_class(depths)) == [0, 0, 1, 1, 2]


def test_peak_hour_is_the_one_with_most_impassable_segments():
    by_segment = np.array([[0.0, 5.0], [40.0, 50.0], [90.0, 5.0], [35.0, 35.0]])
    assert peak_flood_hour(by_segment) == 1
