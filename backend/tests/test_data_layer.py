import numpy as np

from app import config
from app.config import Grid, build_grid
from app.data_fetch import (
    MAX_COORDS_PER_REQUEST,
    chunked,
    idw_weights,
    interpolate_rain,
    is_underpass,
    simplify_line,
    upsample_bilinear,
    way_to_feature,
)

SMALL = Grid(lat_min=25.0, lat_max=25.1, lon_min=55.0, lon_max=55.1, rows=4, cols=5)


def test_grid_is_roughly_150_by_160_at_200m():
    grid = build_grid(200)
    assert grid.shape == (150, 161)


def test_grid_centres_lie_inside_bbox_and_ascend():
    lats, lons = config.GRID.lats(), config.GRID.lons()
    assert lats.shape == (config.GRID.rows,) and lons.shape == (config.GRID.cols,)
    assert config.LAT_MIN < lats[0] < lats[-1] < config.LAT_MAX
    assert config.LON_MIN < lons[0] < lons[-1] < config.LON_MAX


def test_chunked_respects_api_limit():
    chunks = list(chunked(range(250), MAX_COORDS_PER_REQUEST))
    assert [len(c) for c in chunks] == [100, 100, 50]


def test_idw_weights_sum_to_one():
    weights = idw_weights(np.array([25.0, 25.1]), np.array([55.0, 55.1]), SMALL)
    assert weights.shape == (20, 2)
    assert np.allclose(weights.sum(axis=1), 1.0)


def test_interpolated_rain_has_grid_shape_and_stays_within_source_range():
    points = [
        {"lat": 25.0, "lon": 55.0, "precipitation_mm": [0.0, 2.0, 10.0]},
        {"lat": 25.1, "lon": 55.1, "precipitation_mm": [0.0, 6.0, 30.0]},
    ]
    rain = interpolate_rain(points, SMALL)
    assert rain.shape == (3, 4, 5)
    assert np.all(rain[0] == 0.0)
    assert rain[2].min() >= 10.0 and rain[2].max() <= 30.0
    # the cell nearest the south-west source is drier than the north-east one
    assert rain[2, 0, 0] < rain[2, -1, -1]


def test_upsample_bilinear_keeps_samples_and_interpolates_between():
    coarse = np.array([[0.0, 4.0], [8.0, 12.0]])
    rows, cols = np.array([0, 2]), np.array([0, 2])
    full = upsample_bilinear(coarse, rows, cols, (4, 4))
    assert full.shape == (4, 4)
    assert np.array_equal(full[np.ix_(rows, cols)], coarse)
    assert full[1, 1] == 6.0
    # beyond the last sample the edge value is held
    assert np.array_equal(full[3], full[2]) and np.array_equal(full[:, 3], full[:, 2])


def test_simplify_drops_collinear_points_and_keeps_corners():
    straight = [(55.0, 25.0), (55.001, 25.0), (55.002, 25.0)]
    assert simplify_line(straight, 5.0) == [straight[0], straight[-1]]
    corner = [(55.0, 25.0), (55.002, 25.0), (55.002, 25.002)]
    assert simplify_line(corner, 5.0) == corner


def test_underpass_tagging():
    assert is_underpass({"tunnel": "yes"})
    assert is_underpass({"layer": "-1"})
    assert not is_underpass({"bridge": "yes", "layer": "1"})
    assert not is_underpass({"layer": "ground"})
    assert not is_underpass({})


def test_way_to_feature_shape():
    way = {
        "id": 7,
        "geometry": [{"lat": 25.1, "lon": 55.2}, {"lat": 25.11, "lon": 55.21}],
        "tags": {"highway": "primary", "name": "x", "name:en": "Test Road", "tunnel": "yes"},
    }
    feature = way_to_feature(way)
    assert feature["geometry"] == {
        "type": "LineString",
        "coordinates": [[55.2, 25.1], [55.21, 25.11]],
    }
    assert feature["properties"] == {
        "id": 7, "name": "Test Road", "highway": "primary", "underpass": True, "bridge": False,
    }
    assert way_to_feature({"id": 8, "geometry": [], "tags": {"highway": "primary"}}) is None
