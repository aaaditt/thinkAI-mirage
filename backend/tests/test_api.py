import pytest
from fastapi.testclient import TestClient

from app import config
from app.city import RulePlanner
from app.main import create_app


@pytest.fixture(scope="module")
def client(small_world):
    with TestClient(create_app(small_world, RulePlanner())) as test_client:
        yield test_client


def test_meta_describes_the_replay_and_carries_the_disclaimer(client, small_world):
    meta = client.get("/api/meta").json()
    assert meta["disclaimer"] == config.DISCLAIMER
    assert "simulated" in meta["disclaimer"].lower()
    assert meta["bbox"] == [55.0, 25.0, 55.1, 25.1]
    assert (meta["grid_rows"], meta["grid_cols"]) == (10, 10)
    assert (meta["rain_rows"], meta["rain_cols"]) == (3, 3)
    assert meta["segment_count"] == len(small_world.scenario.features)
    assert meta["story"] == {"zero_hour": 14, "start_hour": 8, "end_hour": 16}
    assert [d["name"] for d in meta["districts"]] == list(config.DISTRICTS)


def test_roads_are_geojson_with_ids_matching_risk_string_positions(client, small_world):
    response = client.get("/api/roads")
    assert response.headers["content-type"].startswith("application/geo+json")
    features = response.json()["features"]
    assert [f["id"] for f in features] == list(range(len(small_world.scenario.features)))
    assert features[8]["properties"]["underpass"] is True


def test_replay_frame_shape(client, small_world):
    frame = client.get("/api/replay/14").json()
    n = len(small_world.scenario.features)
    assert frame["hour"] == 14 and frame["offset_hours"] == 0
    assert len(frame["rain_mm"]) == 9
    assert len(frame["rain_forecast_mm"]) == config.FORECAST_LEADS
    assert all(len(lead) == 9 for lead in frame["rain_forecast_mm"])
    for key in ("risk", "risk_uncorrected", "risk_next_6h"):
        assert len(frame[key]) == n and set(frame[key]) <= set("012")
    assert sum(frame["counts"].values()) == n
    assert frame["counts"]["impassable"] == frame["risk"].count("2")
    assert len(frame["sensors"]) == len(small_world.scenario.sensors)
    assert {"id", "lat", "lon", "at_underpass", "depth_cm"} == set(frame["sensors"][0])


def test_offset_is_relative_to_story_zero(client):
    assert client.get("/api/replay/8").json()["offset_hours"] == -6
    assert client.get("/api/replay/16").json()["offset_hours"] == 2


def test_replay_rejects_hours_outside_the_day(client):
    assert client.get("/api/replay/24").status_code == 404
    assert client.get("/api/replay/-1").status_code == 404


def test_same_hour_twice_gives_identical_frames(client):
    assert client.get("/api/replay/10").json() == client.get("/api/replay/10").json()
