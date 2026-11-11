import numpy as np

from app import config
from app.config import Grid
from app.ground import Terrain
from app.sensors import SimulatedDepthSensors, hollowness, place_sensors

GRID = Grid(lat_min=25.0, lat_max=25.1, lon_min=55.0, lon_max=55.1, rows=10, cols=10)


def road(row: int, underpass: bool = False, bridge: bool = False) -> dict:
    lat = 25.005 + 0.01 * row
    return {
        "geometry": {"coordinates": [[55.001, lat], [55.099, lat]]},
        "properties": {"underpass": underpass, "bridge": bridge},
    }


DISTRICTS = {"Low Town": (25.045, 55.045)}


def terrain(land: np.ndarray | None = None) -> Terrain:
    """Flat ground at 2 m with one hollow at row 4, column 4."""
    elevation = np.full(GRID.shape, 2.0)
    elevation[4, 4] = 1.0
    water = np.zeros(GRID.shape, dtype=bool) if land is None else ~land
    return Terrain(elevation_m=elevation, open_water=water, dip_cm=np.zeros(GRID.shape))


def placed(land: np.ndarray | None = None, districts: dict | None = None) -> list:
    features = [road(r) for r in range(0, 8)] + [road(8, underpass=True), road(9, bridge=True)]
    return place_sensors(features, GRID, terrain(land), np.random.default_rng(0),
                         {} if districts is None else districts)


def test_placement_is_repeatable_and_fills_the_configured_count():
    assert placed() == placed()
    assert len(placed()) == config.SENSOR_COUNT
    assert len({(s.row, s.col) for s in placed()}) == config.SENSOR_COUNT


def test_sensors_sit_on_roads_never_on_bridges_and_cover_underpasses():
    sensors = placed()
    assert all(s.row != 9 for s in sensors)  # row 9 is the bridge
    underpass = [s for s in sensors if s.at_underpass]
    assert len(underpass) == 10  # the underpass road crosses 10 cells
    assert all(s.row == 8 for s in underpass)


def test_sensors_avoid_open_water():
    land = np.ones(GRID.shape, dtype=bool)
    land[:, :5] = False
    assert all(s.col >= 5 for s in placed(land))


def test_readings_are_repeatable_non_negative_and_close_to_truth():
    truth = np.full((3, 10, 10), 50.0)
    truth[0] = 0.0
    source = SimulatedDepthSensors(truth, placed())
    wet = source.read(1)
    assert wet == SimulatedDepthSensors(truth, placed()).read(1)
    assert len(wet) == config.SENSOR_COUNT
    assert all(r.depth_cm >= 0.0 for r in source.read(0))
    values = np.array([r.depth_cm for r in wet])
    assert abs(values.mean() - 50.0) < 5.0
    assert values.std() > 0.0  # readings carry noise; they are not the truth itself


def test_hollowness_is_positive_only_in_the_hollow():
    depth = hollowness(terrain().elevation_m)
    assert depth[4, 4] == 1.0 and depth.argmax() == 4 * GRID.cols + 4
    assert depth[0, 0] == 0.0


def test_district_gauges_go_to_the_lowest_road_cells_and_carry_the_district_name():
    sensors = placed(districts=DISTRICTS)
    gauges = [s for s in sensors if s.district == "Low Town"]
    assert len(gauges) == config.SENSOR_PER_DISTRICT
    assert (gauges[0].row, gauges[0].col) == (4, 4)  # the hollow is picked first
    assert not any(s.at_underpass for s in gauges)
    assert len(sensors) == config.SENSOR_COUNT
    assert len({(s.row, s.col) for s in sensors}) == config.SENSOR_COUNT  # no cell used twice
