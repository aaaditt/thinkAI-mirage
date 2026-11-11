import ast
import inspect

import numpy as np
import pytest
from fastapi.testclient import TestClient

import app.shield as shield
from app import config
from app.city import RulePlanner, Session
from app.main import create_app
from app.models import Policy
from app.sensors import Sensor
from app.shield import evaluate_payouts, first_trigger_hour, generate_policies, metres_between
from tests.conftest import SMALL_DISTRICTS

DISTRICTS = {"North": (25.20, 55.30), "South": (25.10, 55.20)}


def gauge(sensor_id: str, district: str | None, lat: float, lon: float) -> Sensor:
    return Sensor(id=sensor_id, lat=lat, lon=lon, row=0, col=0, at_underpass=False,
                  district=district)


GAUGES = [
    gauge("S001", "North", 25.20, 55.30),
    gauge("S002", "North", 25.21, 55.31),
    gauge("S003", "South", 25.10, 55.20),
    gauge("S004", None, 25.15, 55.25),  # a city sensor, not a Shield gauge
]


def policy(sensor_id: str = "S001", threshold: float = 30.0, duration: int = 1,
           amount: int = 20_000, policy_id: str = "P001") -> Policy:
    return Policy(
        id=policy_id, business="Test Bakery (mock)", district="North", lat=25.2, lon=55.3,
        tier="Basic", threshold_cm=threshold, duration_hours=duration, amount_aed=amount,
        sensor_id=sensor_id, sensor_distance_m=120,
    )


# ---------------------------------------------------------------- trigger logic


@pytest.mark.parametrize(
    ("readings", "threshold", "duration", "expected"),
    [
        ([0, 10, 29.9, 12], 30, 1, None),  # never reaches the threshold
        ([0, 10, 30.0, 12], 30, 1, 2),  # exactly at the threshold counts
        ([0, 35, 10, 40, 45], 30, 2, 4),  # a single wet hour is not "sustained"
        ([40, 40, 40], 30, 2, 1),  # pays when the second consecutive hour completes
        ([0, 60, 0], 50, 1, 1),
        ([], 30, 1, None),
    ],
)
def test_first_trigger_hour(readings, threshold, duration, expected):
    assert first_trigger_hour(np.array(readings, dtype=float), threshold, duration) == expected


def test_payout_fires_once_at_the_first_trigger_with_the_measured_depth():
    readings = np.array([[0.0], [12.0], [34.5], [80.0], [90.0]])
    events = evaluate_payouts([policy()], ["S001"], readings)
    assert [e.model_dump() for e in events] == [
        {"policy_id": "P001", "hour": 2, "measured_cm": 34.5, "amount_aed": 20_000}
    ]


def test_each_policy_reads_only_its_own_gauge():
    readings = np.zeros((4, 2))
    readings[1, 1] = 70.0  # only the second gauge gets wet
    policies = [policy("S001", policy_id="P001"), policy("S002", policy_id="P002")]
    events = evaluate_payouts(policies, ["S001", "S002"], readings)
    assert [e.policy_id for e in events] == ["P002"]


def test_events_are_ordered_by_hour():
    readings = np.array([[0.0, 40.0], [40.0, 40.0]])
    policies = [policy("S001", policy_id="P001"), policy("S002", policy_id="P002")]
    events = evaluate_payouts(policies, ["S001", "S002"], readings)
    assert [(e.hour, e.policy_id) for e in events] == [(0, "P002"), (1, "P001")]


def test_no_readings_above_threshold_means_no_payouts():
    assert evaluate_payouts([policy()], ["S001"], np.full((24, 1), 29.0)) == []


def test_shield_cannot_see_the_forecast_or_the_flood_model():
    """The trigger must read only from the independent sensor index."""
    imported = {
        node.module
        for node in ast.walk(ast.parse(inspect.getsource(shield)))
        if isinstance(node, ast.ImportFrom)
    }
    assert imported == {"__future__", "app", "app.models", "app.sensors"}
    assert set(inspect.signature(evaluate_payouts).parameters) == {
        "policies", "sensor_ids", "readings_cm"
    }


# ---------------------------------------------------------------- mock policies


def test_policies_are_repeatable_and_cover_every_district():
    first = generate_policies(GAUGES, np.random.default_rng(1), DISTRICTS)
    assert first == generate_policies(GAUGES, np.random.default_rng(1), DISTRICTS)
    assert len(first) == config.POLICY_COUNT
    assert {p.district for p in first} == set(DISTRICTS)
    assert len({p.id for p in first}) == config.POLICY_COUNT
    assert all("(mock)" in p.business for p in first)


def test_policy_is_indexed_to_the_nearest_gauge_in_its_own_district():
    by_id = {g.id: g for g in GAUGES}
    for p in generate_policies(GAUGES, np.random.default_rng(1), DISTRICTS):
        chosen = by_id[p.sensor_id]
        assert chosen.district == p.district  # never the city sensor or another district
        nearest = min(
            (g for g in GAUGES if g.district == p.district),
            key=lambda g: metres_between(p.lat, p.lon, g.lat, g.lon),
        )
        assert chosen.id == nearest.id
        assert p.sensor_distance_m == round(metres_between(p.lat, p.lon, chosen.lat, chosen.lon))


def test_policies_stay_near_their_district_and_use_configured_tiers():
    tiers = {(name, cm, hours, aed) for name, cm, hours, aed in config.POLICY_TIERS}
    for p in generate_policies(GAUGES, np.random.default_rng(2), DISTRICTS):
        centre = DISTRICTS[p.district]
        assert metres_between(p.lat, p.lon, *centre) <= config.POLICY_RADIUS_KM * 1000 + 5
        assert (p.tier, p.threshold_cm, p.duration_hours, p.amount_aed) in tiers


def test_a_district_without_a_gauge_gets_no_policies():
    only_north = [g for g in GAUGES if g.district == "North"]
    policies = generate_policies(only_north, np.random.default_rng(1), DISTRICTS)
    assert policies and {p.district for p in policies} == {"North"}


# ---------------------------------------------------------------- session and API


@pytest.fixture(scope="module")
def policies(small_world):
    return generate_policies(
        small_world.scenario.sensors, np.random.default_rng(5), SMALL_DISTRICTS
    )


def test_session_payouts_accumulate_and_match_the_sensor_readings(small_world, policies):
    session = Session(small_world, RulePlanner(), policies)
    by_id = {p.id: p for p in policies}
    column = {s.id: i for i, s in enumerate(small_world.scenario.sensors)}
    final = session.payouts(config.HOURS - 1)
    assert final, "the synthetic storm should trigger at least one mock policy"
    for event in final:
        p = by_id[event.policy_id]
        measured = small_world.timeline.sensor_cm[event.hour, column[p.sensor_id]]
        assert event.measured_cm == round(float(measured), 1) >= p.threshold_cm
    for hour in range(config.HOURS):
        assert session.payouts(hour) == [e for e in final if e.hour <= hour]


def test_api_serves_policies_once_and_payouts_with_a_running_total(small_world, policies):
    with TestClient(create_app(small_world, RulePlanner(), policies)) as client:
        meta = client.get("/api/meta").json()
        assert len(meta["policies"]) == len(policies)
        assert {"id", "business", "lat", "lon", "threshold_cm", "sensor_id",
                "sensor_distance_m"} <= set(meta["policies"][0])
        early, late = client.get("/api/replay/0").json(), client.get("/api/replay/23").json()
        assert late["payout_total_aed"] == sum(e["amount_aed"] for e in late["payouts"]) > 0
        assert len(early["payouts"]) <= len(late["payouts"])
        assert all(e["hour"] <= 0 for e in early["payouts"])
