"""Shield engine: mock parametric policies and their payout trigger.

The trigger sees ONLY sensor readings (the independent index from sensors.py).
This module deliberately imports nothing from the forecast or the flood model,
so a payout can never be driven by a prediction.

Policies, businesses and amounts are invented. No real insurer or payment exists.
"""

from __future__ import annotations

import math

import numpy as np

from app import config
from app.models import PayoutEvent, Policy
from app.sensors import Sensor

BUSINESS_TYPES = (
    "Bakery", "Auto Garage", "Pharmacy", "Print Shop", "Cafe",
    "Tailor", "Grocery", "Warehouse", "Laundry", "Phone Repair",
)


def metres_between(lat_a: float, lon_a: float, lat_b: float, lon_b: float) -> float:
    dy = (lat_a - lat_b) * config.METRES_PER_DEG_LAT
    dx = (lon_a - lon_b) * config.METRES_PER_DEG_LAT * math.cos(math.radians(lat_a))
    return math.hypot(dx, dy)


def scatter_near(centre: tuple[float, float], rng: np.random.Generator) -> tuple[float, float]:
    """A random point within POLICY_RADIUS_KM of `centre` (uniform over the disc)."""
    distance_m = config.POLICY_RADIUS_KM * 1000.0 * math.sqrt(rng.random())
    bearing = rng.random() * 2.0 * math.pi
    lat = centre[0] + distance_m * math.cos(bearing) / config.METRES_PER_DEG_LAT
    lon = centre[1] + distance_m * math.sin(bearing) / (
        config.METRES_PER_DEG_LAT * math.cos(math.radians(centre[0]))
    )
    return round(lat, 5), round(lon, 5)


def generate_policies(
    sensors: list[Sensor], rng: np.random.Generator,
    districts: dict[str, tuple[float, float]] | None = None,
) -> list[Policy]:
    """Mock policies spread over the districts, each indexed to the nearest
    gauge in its own district. A district without a gauge gets no policies."""
    districts = config.DISTRICTS if districts is None else districts
    names = list(districts)
    policies = []
    for number in range(1, config.POLICY_COUNT + 1):
        district = names[(number - 1) % len(names)]
        lat, lon = scatter_near(districts[district], rng)
        tier, threshold, duration, amount = config.POLICY_TIERS[
            int(rng.integers(len(config.POLICY_TIERS)))
        ]
        business = f"{district} {BUSINESS_TYPES[int(rng.integers(len(BUSINESS_TYPES)))]}"
        gauges = [s for s in sensors if s.district == district]
        if not gauges:
            continue
        gauge = min(gauges, key=lambda s: metres_between(lat, lon, s.lat, s.lon))
        policies.append(Policy(
            id=f"P{number:03d}", business=f"{business} {number:02d} (mock)", district=district,
            lat=lat, lon=lon, tier=tier, threshold_cm=threshold, duration_hours=duration,
            amount_aed=amount, sensor_id=gauge.id,
            sensor_distance_m=round(metres_between(lat, lon, gauge.lat, gauge.lon)),
        ))
    return policies


def first_trigger_hour(readings_cm: np.ndarray, threshold_cm: float, duration: int) -> int | None:
    """First hour that completes `duration` consecutive readings at or above the threshold."""
    run = 0
    for hour, depth in enumerate(readings_cm):
        run = run + 1 if depth >= threshold_cm else 0
        if run >= duration:
            return hour
    return None


def evaluate_payouts(
    policies: list[Policy], sensor_ids: list[str], readings_cm: np.ndarray
) -> list[PayoutEvent]:
    """Payout events for the whole day, ordered by hour.

    `readings_cm` is (hours, sensors): what a DepthSensorSource measured, in the
    order of `sensor_ids`. Each policy pays at most once.
    """
    column = {sensor_id: i for i, sensor_id in enumerate(sensor_ids)}
    events = []
    for policy in policies:
        series = readings_cm[:, column[policy.sensor_id]]
        hour = first_trigger_hour(series, policy.threshold_cm, policy.duration_hours)
        if hour is not None:
            events.append(PayoutEvent(
                policy_id=policy.id, hour=hour, measured_cm=round(float(series[hour]), 1),
                amount_aed=policy.amount_aed,
            ))
    return sorted(events, key=lambda event: (event.hour, event.policy_id))
