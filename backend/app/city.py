"""City engine: an agent proposes actions; only a human approval gives them effect.

Planners return proposals. `validate_plan` enforces the hard rules on every
planner's output. `Session` holds the queue; the simulation is only ever given
APPROVED actions, so a proposed or rejected action cannot change anything.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from pydantic import ValidationError

from app import config
from app.ground import cells_by_segment, format_depth
from app.models import (
    Action,
    Alert,
    AtRiskSite,
    Depot,
    DistrictOutlook,
    Evidence,
    Inventory,
    Plan,
    PlanResult,
    PayoutEvent,
    Policy,
    ProposedAction,
    Situation,
)
from app.replay import Scenario, Timeline, World, build_timeline
from app.shield import evaluate_payouts, generate_policies

log = logging.getLogger("mirage.city")

TIME_PATTERN = re.compile(r"\b\d{1,2}:\d{2}\b")
ROUTE_WORDS = re.compile(r"\b(route|via|detour|take the|use the)\b", re.IGNORECASE)


class PlanError(ValueError):
    """A plan broke one of the hard rules."""


class ActionError(ValueError):
    """A human decision could not be applied (unknown id, already decided, no pumps)."""


LAST_HOUR = config.HOURS - 1


def clock(hour: int) -> str:
    return f"{min(hour, LAST_HOUR):02d}:00"


def confidence_for(lead_hours: int) -> float:
    """Heuristic: forecast error is built to grow by FORECAST_NOISE_PER_LEAD per hour."""
    return round(max(0.05, 0.95 - config.FORECAST_NOISE_PER_LEAD * lead_hours), 2)


# ---------------------------------------------------------------- sites


@dataclass(frozen=True)
class Sites:
    """Road segments grouped into sites: one per road (OSM way), and one per
    physical underpass (its carriageways are separate ways that share grid cells)."""

    targets: list[str]  # "U<way id>" for underpasses, "R<way id>" for other roads
    cells: list[np.ndarray]  # grid cells of each site
    labels: list[str]
    underpass: np.ndarray  # (sites,) bool
    bridge: np.ndarray  # (sites,) bool
    districts: list[str | None]
    lat: np.ndarray
    lon: np.ndarray
    order: np.ndarray  # segment indices sorted by site
    starts: np.ndarray  # where each site begins in `order`
    in_district: dict[str, np.ndarray]  # district name -> bool mask over segments

    def position(self, target: str) -> int:
        return self.targets.index(target)

    def segments(self, target: str) -> np.ndarray:
        site = self.position(target)
        end = self.starts[site + 1] if site + 1 < len(self.starts) else len(self.order)
        return self.order[self.starts[site] : end]

    def deepest(self, per_segment: np.ndarray) -> np.ndarray:
        """Deepest segment of each site; works on (..., segments) arrays."""
        return np.maximum.reduceat(per_segment[..., self.order], self.starts, axis=-1)


def km_between(lat_a: np.ndarray, lon_a: np.ndarray, lat_b: float, lon_b: float) -> np.ndarray:
    dy = (lat_a - lat_b) * config.METRES_PER_DEG_LAT
    dx = (lon_a - lon_b) * config.METRES_PER_DEG_LAT * math.cos(math.radians(lat_b))
    return np.hypot(dx, dy) / 1000.0


def nearest_district(lat: float, lon: float) -> str | None:
    best = min(
        config.DISTRICTS.items(),
        key=lambda item: km_between(np.array(lat), np.array(lon), *item[1]),
    )
    near = km_between(np.array(lat), np.array(lon), *best[1]) <= config.DISTRICT_RADIUS_KM
    return best[0] if near else None


def site_label(name: str, underpass: bool, district: str | None, lat: float, lon: float) -> str:
    kind = "underpass" if underpass else "road"
    base = f"{name} {kind}" if name and underpass else name or f"Unnamed {kind}"
    return f"{base}, {district}" if district else f"{base} ({lat:.3f}, {lon:.3f})"


def underpass_groups(way_ids: np.ndarray, underpass: np.ndarray,
                     cells: list[np.ndarray]) -> np.ndarray:
    """Group key per segment: its way id, except that underpass ways sharing a
    grid cell are merged under the smallest way id among them."""
    parent = {int(w): int(w) for w in np.unique(way_ids[underpass])}

    def root(way: int) -> int:
        while parent[way] != way:
            parent[way] = parent[parent[way]]
            way = parent[way]
        return way

    owner: dict[int, int] = {}
    for segment in np.flatnonzero(underpass):
        way = root(int(way_ids[segment]))
        for cell in map(int, cells[segment]):
            other = root(owner.setdefault(cell, way))
            if other != way:
                low, high = sorted((way, other))
                parent[high] = low
                way = low
    keys = way_ids.copy()
    for segment in np.flatnonzero(underpass):
        keys[segment] = root(int(way_ids[segment]))
    return keys


def build_sites(scenario: Scenario) -> Sites:
    features = scenario.features
    mid = np.array([f["geometry"]["coordinates"][len(f["geometry"]["coordinates"]) // 2]
                    for f in features])
    way_ids = np.array([f["properties"]["id"] for f in features])
    is_underpass = np.array([f["properties"]["underpass"] and not f["properties"]["bridge"]
                             for f in features])
    segment_cells = cells_by_segment(scenario.index)
    keys = underpass_groups(way_ids, is_underpass, segment_cells)
    order = np.argsort(keys, kind="stable")
    starts = np.flatnonzero(np.diff(keys[order], prepend=-1))
    ends = np.append(starts[1:], order.size)
    targets, labels, districts, lats, lons, underpass, bridge, cells = ([] for _ in range(8))
    for start, end in zip(starts, ends):
        members = order[start:end]
        centre = members[len(members) // 2]
        props = features[centre]["properties"]
        named = next((features[m]["properties"]["name"] for m in members
                      if features[m]["properties"]["name"]), "")
        lon, lat = float(mid[centre, 0]), float(mid[centre, 1])
        district = nearest_district(lat, lon)
        targets.append(("U" if is_underpass[centre] else "R") + str(keys[centre]))
        labels.append(site_label(named, bool(is_underpass[centre]), district, lat, lon))
        districts.append(district)
        lats.append(lat)
        lons.append(lon)
        underpass.append(bool(is_underpass[centre]))
        bridge.append(props["bridge"])
        cells.append(np.unique(np.concatenate([segment_cells[m] for m in members])))
    return Sites(
        targets=targets, cells=cells, labels=labels, underpass=np.array(underpass),
        bridge=np.array(bridge), districts=districts, lat=np.array(lats), lon=np.array(lons),
        order=order, starts=starts,
        in_district={
            name: km_between(mid[:, 1], mid[:, 0], lat, lon) <= config.DISTRICT_RADIUS_KM
            for name, (lat, lon) in config.DISTRICTS.items()
        },
    )


# ---------------------------------------------------------------- situation


def site_outlook(sites: Sites, site: int, now: np.ndarray, ahead: np.ndarray) -> AtRiskSite:
    """`now` is (sites,), `ahead` is (leads, sites)."""
    forecast = ahead[:, site]
    flooded = np.flatnonzero(forecast > config.IMPASSABLE_DEPTH_CM)
    if now[site] > config.IMPASSABLE_DEPTH_CM:
        lead = 0
    else:
        lead = int(flooded[0]) + 1 if flooded.size else None
    return AtRiskSite(
        target=sites.targets[site],
        label=sites.labels[site],
        underpass=bool(sites.underpass[site]),
        district=sites.districts[site],
        depth_now_cm=round(float(now[site]), 1),
        forecast_peak_cm=round(float(forecast.max()), 1),
        peak_lead_hours=int(forecast.argmax()) + 1,
        impassable_lead_hours=lead,
    )


def pick_sites(sites: Sites, now: np.ndarray, ahead: np.ndarray) -> list[int]:
    """Underpasses about to flood first (soonest first), then the deepest roads."""
    peak = ahead.max(axis=0)
    at_risk = (peak > config.IMPASSABLE_DEPTH_CM) & ~sites.bridge
    first_lead = np.where(
        now > config.IMPASSABLE_DEPTH_CM, 0,
        (ahead > config.IMPASSABLE_DEPTH_CM).argmax(axis=0) + 1,
    )
    upcoming = first_lead > 0
    under = np.flatnonzero(at_risk & sites.underpass)
    # Sort keys, last is primary: not-yet-flooded first, then soonest, then deepest.
    under = under[np.lexsort((-peak[under], first_lead[under], ~upcoming[under]))]
    roads = np.flatnonzero(at_risk & ~sites.underpass)
    roads = roads[np.argsort(-peak[roads], kind="stable")]
    return [int(s) for s in under[: config.PLAN_TOP_UNDERPASSES]] + [
        int(s) for s in roads[: config.PLAN_TOP_ROADS]
    ]


def district_outlooks(sites: Sites, timeline: Timeline, hour: int) -> list[DistrictOutlook]:
    now, ahead = timeline.segment_cm[hour], timeline.segment_forecast_cm[hour]
    out = []
    for name, inside in sites.in_district.items():
        out.append(DistrictOutlook(
            name=name,
            impassable_now=int((now[inside] > config.IMPASSABLE_DEPTH_CM).sum()),
            impassable_by_lead=[
                int(n) for n in (ahead[:, inside] > config.IMPASSABLE_DEPTH_CM).sum(axis=1)
            ],
            deepest_now_cm=round(float(now[inside].max(initial=0.0)), 1),
            deepest_forecast_cm=round(float(ahead[:, inside].max(initial=0.0)), 1),
        ))
    return out


def is_active(action: Action, hour: int) -> bool:
    """True if an APPROVED action is in force at `hour`."""
    return (
        action.status == "approved"
        and action.start_hour <= hour
        and (action.end_hour is None or hour < action.end_hour)
    )


def build_inventory(actions: list[Action]) -> Inventory:
    staged = sum(a.type == "stage_pump" and a.status == "approved" for a in actions)
    return Inventory(
        pumps_total=config.PUMP_COUNT,
        pumps_available=config.PUMP_COUNT - staged,
        tankers_total=config.TANKER_COUNT,
        depots=[
            Depot(name=name, lat=lat, lon=lon, pumps=pumps, tankers=tankers)
            for name, (lat, lon, pumps, tankers) in config.DEPOTS.items()
        ],
    )


def build_situation(
    sites: Sites, timeline: Timeline, hour: int, actions: list[Action]
) -> Situation:
    now = sites.deepest(timeline.segment_cm[hour])
    ahead = sites.deepest(timeline.segment_forecast_cm[hour])
    closed = [
        a.target for a in actions if a.type == "close_underpass" and is_active(a, hour)
    ]
    return Situation(
        hour=hour,
        clock=clock(hour),
        sites=[site_outlook(sites, s, now, ahead) for s in pick_sites(sites, now, ahead)],
        closed_sites=[site_outlook(sites, sites.position(t), now, ahead) for t in closed],
        districts=district_outlooks(sites, timeline, hour),
        inventory=build_inventory(actions),
        actions=actions,
    )


# ---------------------------------------------------------------- hard rules


def live(actions: list[Action], kind: str, target: str) -> list[Action]:
    """Earlier actions of this kind on this target that were not rejected."""
    return [a for a in actions if a.type == kind and a.target == target
            and a.status != "rejected"]


def check_alert(action: ProposedAction, situation: Situation) -> None:
    district = next((d for d in situation.districts if d.name == action.target), None)
    if district is None:
        raise PlanError(f"alert target {action.target!r} is not a known district")
    message = action.message or ""
    if not message or len(message) > config.ALERT_MAX_CHARS:
        raise PlanError(f"alert text must be 1-{config.ALERT_MAX_CHARS} characters")
    if district.name not in message:
        raise PlanError("alert text must name its district")
    if not TIME_PATTERN.search(message):
        raise PlanError("alert text must give a concrete time (HH:MM)")
    named_roads = [s.label.split(",")[0] for s in situation.sites if "Unnamed" not in s.label]
    if ROUTE_WORDS.search(message) or any(road in message for road in named_roads):
        raise PlanError("alerts must be area-based, never route-based")
    already_deep = district.deepest_now_cm > config.IMPASSABLE_DEPTH_CM
    if action.evidence.lead_hours < config.ALERT_MIN_LEAD_HOURS and not already_deep:
        raise PlanError("alert lead time is under 1 hour and the district is not flooded yet")
    for earlier in live(situation.actions, "area_alert", action.target):
        if abs(action.start_hour - earlier.start_hour) < config.ALERT_SPACING_HOURS:
            raise PlanError(
                f"more than one alert for {district.name} within "
                f"{config.ALERT_SPACING_HOURS} hours"
            )


def validate_plan(situation: Situation, proposals: list[ProposedAction]) -> None:
    """Raise PlanError if the plan breaks any hard rule. Applied to every planner."""
    known = {s.target: s for s in situation.sites}
    closed = {s.target for s in situation.closed_sites}
    seen: set[tuple[str, str]] = set()
    for action in proposals:
        if (action.type, action.target) in seen:
            raise PlanError(f"duplicate {action.type} for {action.target}")
        seen.add((action.type, action.target))
        if action.start_hour < situation.hour:
            raise PlanError("an action cannot start in the past")
        if action.type == "area_alert":
            check_alert(action, situation)
        elif action.type == "open_road":
            if action.target not in closed:
                raise PlanError(f"{action.target} is not currently closed")
        elif action.target not in known:
            raise PlanError(f"{action.target!r} is not one of the at-risk sites")
        elif action.type == "close_underpass" and not known[action.target].underpass:
            raise PlanError(f"{action.target} is not an underpass")
    pumps = sum(a.type == "stage_pump" for a in proposals)
    if pumps > situation.inventory.pumps_available:
        raise PlanError(
            f"plan stages {pumps} pumps but only "
            f"{situation.inventory.pumps_available} are available"
        )


def drop_repeats(situation: Situation, proposals: list[ProposedAction]) -> list[ProposedAction]:
    """Leave out proposals that repeat an earlier, still-live closure or pump."""
    return [
        p for p in proposals
        if p.type == "area_alert" or not live(situation.actions, p.type, p.target)
    ]


# ---------------------------------------------------------------- planners


class Planner(Protocol):
    name: str

    def plan(self, situation: Situation) -> list[ProposedAction]: ...


class RulePlanner:
    """Deterministic planner. Always available, needs no network."""

    name = "rules"

    def plan(self, situation: Situation) -> list[ProposedAction]:
        return (
            self._closures(situation)
            + self._pumps(situation)
            + self._alerts(situation)
            + self._reopenings(situation)
        )

    def _closures(self, situation: Situation) -> list[ProposedAction]:
        out = []
        for site in situation.sites:
            lead = site.impassable_lead_hours
            if not site.underpass or lead is None:
                continue
            if live(situation.actions, "close_underpass", site.target):
                continue
            if lead == 0:
                reason = f"Already impassable ({format_depth(site.depth_now_cm)} modelled)."
            else:
                reason = (
                    f"Forecast to pass {config.IMPASSABLE_DEPTH_CM:.0f} cm in {lead} h "
                    f"(peak {format_depth(site.forecast_peak_cm)}). Close before the water arrives."
                )
            out.append(ProposedAction(
                type="close_underpass", target=site.target,
                start_hour=min(situation.hour + max(lead - 1, 0), LAST_HOUR), reason=reason,
                evidence=Evidence(forecast_depth_cm=site.forecast_peak_cm, lead_hours=lead,
                                  confidence=confidence_for(lead)),
            ))
        return out[: config.MAX_CLOSURES_PER_PLAN]

    def _pumps(self, situation: Situation) -> list[ProposedAction]:
        limit = min(config.MAX_PUMPS_PER_PLAN, situation.inventory.pumps_available)
        out = []
        for site in situation.sites:
            lead = site.impassable_lead_hours
            if not site.underpass or lead is None or lead < config.PUMP_MIN_LEAD_HOURS:
                continue
            if live(situation.actions, "stage_pump", site.target):
                continue
            out.append(ProposedAction(
                type="stage_pump", target=site.target,
                start_hour=min(situation.hour + 1, LAST_HOUR),
                reason=(
                    f"Forecast to flood in {lead} h (peak {format_depth(site.forecast_peak_cm)}). "
                    "There is time to stage a pump first."
                ),
                evidence=Evidence(forecast_depth_cm=site.forecast_peak_cm, lead_hours=lead,
                                  confidence=confidence_for(lead)),
            ))
        return out[:limit]

    def _alerts(self, situation: Situation) -> list[ProposedAction]:
        out = []
        for district in situation.districts:
            rise = [n - district.impassable_now for n in district.impassable_by_lead]
            leads = [k for k, extra in enumerate(rise, start=1)
                     if extra >= config.ALERT_MIN_NEW_SEGMENTS]
            recent = [
                a for a in live(situation.actions, "area_alert", district.name)
                if abs(situation.hour - a.start_hour) < config.ALERT_SPACING_HOURS
            ]
            if not leads or recent:
                continue
            lead = leads[0]
            out.append(ProposedAction(
                type="area_alert", target=district.name, start_hour=situation.hour,
                reason=(
                    f"{rise[lead - 1]} more road segments forecast impassable in "
                    f"{district.name} within {lead} h ({district.impassable_now} now)."
                ),
                evidence=Evidence(forecast_depth_cm=district.deepest_forecast_cm,
                                  lead_hours=lead, confidence=confidence_for(lead)),
                message=alert_text(district.name, situation.hour, lead),
            ))
        return out

    def _reopenings(self, situation: Situation) -> list[ProposedAction]:
        out = []
        for site in situation.closed_sites:
            if max(site.depth_now_cm, site.forecast_peak_cm) >= config.CAUTION_DEPTH_CM:
                continue
            if live(situation.actions, "open_road", site.target):
                continue
            out.append(ProposedAction(
                type="open_road", target=site.target, start_hour=situation.hour,
                reason=(
                    f"Now {format_depth(site.depth_now_cm)} and forecast to stay under "
                    f"{config.CAUTION_DEPTH_CM:.0f} cm for 6 h."
                ),
                evidence=Evidence(forecast_depth_cm=site.forecast_peak_cm, lead_hours=0,
                                  confidence=confidence_for(config.FORECAST_LEADS)),
            ))
        return out


def alert_text(district: str, hour: int, lead: int) -> str:
    """Area-based, under 160 characters, with a concrete time."""
    start = clock(hour + lead)
    if lead >= 2:
        return (f"Flooding expected in {district} from ~{start}. Avoid underpasses. "
                f"Delay travel, or leave before {clock(hour + lead - 1)}.")
    return f"Flooding expected in {district} from ~{start}. Avoid underpasses. Delay travel."


Complete = Callable[[str, str], str]  # (system prompt, user prompt) -> raw JSON text

SYSTEM_PROMPT = """You are the planning agent of Mirage, a flood-response prototype for Dubai.
You propose actions. A human approves or rejects each one; you never act yourself.

Reply with one JSON object matching this schema and nothing else:
{schema}

Hard rules (a plan that breaks any of them is discarded):
- "target" must be a site "target" value from the situation (stage_pump, close_underpass),
  a currently closed site (open_road), or a district "name" (area_alert).
- close_underpass only for sites where "underpass" is true.
- Stage at most {max_pumps} pumps and never more than inventory.pumps_available.
- area_alert needs "message": area-based (name the district, never a road or route),
  at most {max_chars} characters, with a concrete time written HH:MM.
- No area_alert with lead_hours under 1 unless the district's deepest_now_cm is over 30.
- At most one area_alert per district per {spacing} hours (check "actions").
- start_hour must be >= the situation hour. Do not repeat an action that is already
  proposed or approved.
- evidence.forecast_depth_cm and lead_hours must come from the situation data.
  confidence is 0-1 and should fall as lead_hours grows.
- Keep each "reason" to one or two plain sentences that cite the numbers."""


class LLMPlanner:
    """Planner backed by an LLM. Its output is untrusted until validated."""

    name = "llm"

    def __init__(self, complete: Complete):
        self._complete = complete

    def plan(self, situation: Situation) -> list[ProposedAction]:
        system = SYSTEM_PROMPT.format(
            schema=json.dumps(Plan.model_json_schema()),
            max_pumps=config.MAX_PUMPS_PER_PLAN,
            max_chars=config.ALERT_MAX_CHARS,
            spacing=config.ALERT_SPACING_HOURS,
        )
        raw = self._complete(system, situation.model_dump_json())
        return Plan.model_validate_json(raw).actions


def azure_complete() -> Complete | None:
    """Chat-completion call for Azure OpenAI, or None when the keys are not set."""
    endpoint = os.environ.get("AZURE_OPENAI_ENDPOINT")
    key = os.environ.get("AZURE_OPENAI_API_KEY")
    deployment = os.environ.get("AZURE_OPENAI_DEPLOYMENT")
    if not (endpoint and key and deployment):
        return None
    from openai import AzureOpenAI  # imported here so the offline demo never needs it

    client = AzureOpenAI(
        azure_endpoint=endpoint, api_key=key, api_version=config.AZURE_OPENAI_API_VERSION
    )

    def complete(system: str, user: str) -> str:
        response = client.chat.completions.create(
            model=deployment,
            messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
        )
        return response.choices[0].message.content or ""

    return complete


def default_planner() -> Planner:
    complete = azure_complete()
    return LLMPlanner(complete) if complete else RulePlanner()


def run_planner(
    planner: Planner, situation: Situation
) -> tuple[str, str | None, list[ProposedAction]]:
    """Plan and validate. Any failure of a non-rule planner falls back to RulePlanner.

    Returns (planner name used, fallback reason or None, proposals).
    """
    fallback = RulePlanner()
    try:
        proposals = drop_repeats(situation, planner.plan(situation))
        validate_plan(situation, proposals)
        return planner.name, None, proposals
    except Exception as error:  # noqa: BLE001 - network, JSON, schema and rule errors alike
        if planner.name == fallback.name:
            raise
        reason = f"{type(error).__name__}: {error}"[:300]
        log.warning("LLM plan rejected, using RulePlanner. %s", reason)
    proposals = drop_repeats(situation, fallback.plan(situation))
    validate_plan(situation, proposals)
    return fallback.name, reason, proposals


# ---------------------------------------------------------------- alerts


class AlertChannel(Protocol):
    """Where approved alerts go. A real channel could implement this later."""

    def send(self, alert: Alert) -> None: ...


class InAppAlertChannel:
    """Keeps alerts in memory for the screen. Nothing leaves this process."""

    def __init__(self) -> None:
        self.sent: list[Alert] = []

    def send(self, alert: Alert) -> None:
        self.sent.append(alert)


# ---------------------------------------------------------------- session


def pump_drainage(scenario: Scenario, sites: Sites, actions: list[Action]) -> np.ndarray | None:
    """Extra drainage (hours, rows, cols) from APPROVED pumps only; None if there are none.

    One pump's capacity is shared across the cells of its site.
    """
    pumps = [a for a in actions if a.type == "stage_pump" and a.status == "approved"]
    if not pumps:
        return None
    extra = np.zeros((scenario.hours, scenario.grid.rows * scenario.grid.cols))
    for action in pumps:
        cells = sites.cells[sites.position(action.target)]
        extra[action.start_hour :, cells] += config.PUMP_DRAINAGE_CM_PER_HOUR / cells.size
    return extra.reshape(scenario.hours, *scenario.grid.shape)


class Session:
    """The live replay: the action queue and the timeline it produces."""

    def __init__(self, world: World, planner: Planner | None = None,
                 policies: list[Policy] | None = None):
        self.world = world
        self.sites = build_sites(world.scenario)
        self.planner = planner or default_planner()
        self.policies = policies if policies is not None else generate_policies(
            world.scenario.sensors, np.random.default_rng(config.SEED)
        )
        self._lock = threading.Lock()
        self.reset()

    def reset(self) -> None:
        with self._lock:
            self.actions: list[Action] = []
            self.channel = InAppAlertChannel()
            self._timeline = self.world.timeline
            self._stale = False

    @property
    def timeline(self) -> Timeline:
        """The timeline under the approved actions. Rebuilt on first use after a
        pump approval, so approving several pumps in a row costs one rebuild."""
        if self._stale:
            extra = pump_drainage(self.world.scenario, self.sites, self.actions)
            self._timeline = build_timeline(self.world.scenario, extra)
            self._stale = False
        return self._timeline

    def situation(self, hour: int) -> Situation:
        return build_situation(self.sites, self.timeline, hour, self.actions)

    def plan(self, hour: int) -> PlanResult:
        with self._lock:
            situation = self.situation(hour)
            name, reason, proposals = run_planner(self.planner, situation)
            queued = [self._queue(p, hour) for p in proposals]
            return PlanResult(planner=name, fallback_reason=reason, actions=queued)

    def _queue(self, proposal: ProposedAction, hour: int) -> Action:
        if proposal.type == "area_alert":
            lat, lon = config.DISTRICTS[proposal.target]
            label = proposal.target
        else:
            site = self.sites.position(proposal.target)
            lat, lon = float(self.sites.lat[site]), float(self.sites.lon[site])
            label = self.sites.labels[site]
        action = Action(
            **proposal.model_dump(), id=f"A{len(self.actions) + 1:03d}", label=label,
            lat=round(lat, 5), lon=round(lon, 5), proposed_hour=hour,
        )
        self.actions.append(action)
        return action

    def decide(self, action_id: str, approve: bool) -> Action:
        """The ONLY place an action's status changes, and only by an explicit call."""
        with self._lock:
            action = next((a for a in self.actions if a.id == action_id), None)
            if action is None:
                raise ActionError(f"no action {action_id}")
            if action.status != "proposed":
                raise ActionError(f"{action_id} was already {action.status}")
            if not approve:
                action.status = "rejected"
                return action
            if (action.type == "stage_pump"
                    and build_inventory(self.actions).pumps_available < 1):
                raise ActionError("no pumps left to stage")
            action.status = "approved"
            self._apply(action)
            return action

    def _apply(self, action: Action) -> None:
        if action.type == "stage_pump":
            self._stale = True
        elif action.type == "area_alert":
            self.channel.send(Alert(
                action_id=action.id, district=action.target,
                message=action.message or "", issued_hour=action.start_hour,
            ))
        elif action.type == "open_road":
            for closure in self.actions:
                if (closure.type == "close_underpass" and closure.target == action.target
                        and closure.status == "approved" and closure.end_hour is None):
                    closure.end_hour = action.start_hour

    def closed_segments(self, hour: int) -> list[int]:
        closed = [a for a in self.actions if a.type == "close_underpass" and is_active(a, hour)]
        return sorted(int(s) for a in closed for s in self.sites.segments(a.target))

    def alerts(self, hour: int) -> list[Alert]:
        return [alert for alert in self.channel.sent if alert.issued_hour <= hour]

    def payouts(self, hour: int) -> list[PayoutEvent]:
        """Payouts fired up to `hour`. Shield is handed the sensor readings and
        nothing else: no forecast, no model depth."""
        sensor_ids = [s.id for s in self.world.scenario.sensors]
        events = evaluate_payouts(self.policies, sensor_ids, self.timeline.sensor_cm)
        return [event for event in events if event.hour <= hour]
