import json

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import config
from app.city import (
    ActionError,
    LLMPlanner,
    PlanError,
    RulePlanner,
    Session,
    alert_text,
    build_sites,
    pump_drainage,
    run_planner,
    underpass_groups,
    validate_plan,
)
from app.main import create_app
from app.models import (
    Action,
    AtRiskSite,
    DistrictOutlook,
    Evidence,
    Inventory,
    ProposedAction,
    Situation,
)

UNDERPASS = "U1008"  # the one underpass road in the small synthetic world
EVIDENCE = Evidence(forecast_depth_cm=60.0, lead_hours=3, confidence=0.7)


def site(target: str, underpass: bool = True, now: float = 5.0, peak: float = 60.0,
         lead: int | None = 3, label: str = "Test Road underpass, Al Barsha") -> AtRiskSite:
    return AtRiskSite(
        target=target, label=label, underpass=underpass, district="Al Barsha",
        depth_now_cm=now, forecast_peak_cm=peak, peak_lead_hours=4, impassable_lead_hours=lead,
    )


def district(name: str = "Al Barsha", now: int = 2, ahead: tuple[int, ...] = (2, 3, 9, 12, 12, 12),
             deepest_now: float = 20.0) -> DistrictOutlook:
    return DistrictOutlook(
        name=name, impassable_now=now, impassable_by_lead=list(ahead),
        deepest_now_cm=deepest_now, deepest_forecast_cm=80.0,
    )


def situation(sites=None, districts=None, actions=None, closed=None, pumps: int = 12,
              hour: int = 10) -> Situation:
    return Situation(
        hour=hour, clock=f"{hour:02d}:00",
        sites=[site("U1"), site("U2", lead=1), site("R9", underpass=False)]
        if sites is None else sites,
        closed_sites=closed or [],
        districts=[district()] if districts is None else districts,
        inventory=Inventory(pumps_total=12, pumps_available=pumps, tankers_total=6, depots=[]),
        actions=actions or [],
    )


def proposal(kind: str = "stage_pump", target: str = "U1", start: int = 11,
             message: str | None = None, evidence: Evidence = EVIDENCE) -> ProposedAction:
    return ProposedAction(type=kind, target=target, start_hour=start, reason="because",
                          evidence=evidence, message=message)


def queued(kind: str, target: str, status: str = "proposed", start: int = 10) -> Action:
    return Action(
        **proposal(kind, target, start, message="x").model_dump(), id="A001", status=status,
        label=target, lat=25.1, lon=55.2, proposed_hour=start,
    )


GOOD_ALERT = "Flooding expected in Al Barsha from ~13:00. Avoid underpasses. Delay travel."


# ---------------------------------------------------------------- RulePlanner


def test_rule_planner_closes_underpasses_before_the_water_arrives():
    plan = RulePlanner().plan(situation())
    closures = {a.target: a for a in plan if a.type == "close_underpass"}
    assert set(closures) == {"U1", "U2"}  # R9 is not an underpass
    assert closures["U1"].start_hour == 12  # floods in 3 h, so close 1 h ahead of that
    assert closures["U2"].start_hour == 10  # floods in 1 h, so close now
    assert closures["U1"].evidence.lead_hours == 3


def test_rule_planner_stages_pumps_only_where_there_is_time_and_stock():
    pumps = [a for a in RulePlanner().plan(situation()) if a.type == "stage_pump"]
    assert [a.target for a in pumps] == ["U1"]  # U2 floods in 1 h: too late to stage
    assert not [a for a in RulePlanner().plan(situation(pumps=0)) if a.type == "stage_pump"]


def test_rule_planner_never_plans_more_pumps_than_the_cap():
    many = [site(f"U{i}") for i in range(8)]
    pumps = [a for a in RulePlanner().plan(situation(sites=many)) if a.type == "stage_pump"]
    assert len(pumps) == config.MAX_PUMPS_PER_PLAN


def test_rule_planner_does_not_repeat_live_actions_but_may_retry_rejected_ones():
    live = situation(actions=[queued("close_underpass", "U1", "approved")])
    assert "U1" not in [a.target for a in RulePlanner().plan(live) if a.type == "close_underpass"]
    rejected = situation(actions=[queued("close_underpass", "U1", "rejected")])
    assert "U1" in [a.target for a in RulePlanner().plan(rejected)
                    if a.type == "close_underpass"]


def test_rule_planner_alert_is_area_based_short_and_timed():
    alerts = [a for a in RulePlanner().plan(situation()) if a.type == "area_alert"]
    assert len(alerts) == 1
    alert = alerts[0]
    assert alert.target == "Al Barsha" and alert.evidence.lead_hours == 3
    assert alert.message == (
        "Flooding expected in Al Barsha from ~13:00. Avoid underpasses. "
        "Delay travel, or leave before 12:00."
    )
    assert len(alert.message) <= config.ALERT_MAX_CHARS


def test_alert_text_fits_the_limit_for_every_district_and_hour():
    for name in config.DISTRICTS:
        for hour in range(config.HOURS):
            for lead in range(1, config.FORECAST_LEADS + 1):
                assert len(alert_text(name, hour, lead)) <= config.ALERT_MAX_CHARS


def test_rule_planner_sends_no_alert_without_a_forecast_rise_or_within_three_hours():
    flat = situation(districts=[district(ahead=(2, 2, 3, 3, 3, 3))])
    assert not [a for a in RulePlanner().plan(flat) if a.type == "area_alert"]
    recent = situation(actions=[queued("area_alert", "Al Barsha", "approved", start=8)])
    assert not [a for a in RulePlanner().plan(recent) if a.type == "area_alert"]
    old = situation(actions=[queued("area_alert", "Al Barsha", "approved", start=7)])
    assert [a for a in RulePlanner().plan(old) if a.type == "area_alert"]


def test_rule_planner_reopens_a_closed_underpass_only_when_it_is_dry_and_stays_dry():
    dry = situation(sites=[], districts=[], closed=[site("U1", now=2.0, peak=4.0, lead=None)])
    assert [(a.type, a.target) for a in RulePlanner().plan(dry)] == [("open_road", "U1")]
    wet = situation(sites=[], districts=[], closed=[site("U1", now=2.0, peak=40.0)])
    assert not RulePlanner().plan(wet)


# ---------------------------------------------------------------- hard rules


@pytest.mark.parametrize(
    "bad",
    [
        [proposal(target="U404")],  # not an at-risk site
        [proposal("close_underpass", "R9")],  # not an underpass
        [proposal(start=9)],  # starts in the past
        [proposal(), proposal()],  # duplicate
        [proposal("open_road", "U1", 10)],  # not closed
        [proposal("area_alert", "Atlantis", 10, GOOD_ALERT)],  # unknown district
        [proposal("area_alert", "Al Barsha", 10, None)],  # no text
        [proposal("area_alert", "Al Barsha", 10, GOOD_ALERT + " x" * 80)],  # too long
        [proposal("area_alert", "Al Barsha", 10, "Flooding expected in Al Barsha soon.")],
        [proposal("area_alert", "Al Barsha", 10, "Flooding from ~13:00. Stay home.")],
        [proposal("area_alert", "Al Barsha", 10,
                  "Al Barsha flooding from ~13:00. Take the E11 route instead.")],
        [proposal("area_alert", "Al Barsha", 10,
                  "Al Barsha: Test Road underpass floods ~13:00.")],  # names a road
        [proposal("area_alert", "Al Barsha", 10, GOOD_ALERT,
                  Evidence(forecast_depth_cm=60, lead_hours=0, confidence=0.9))],  # no lead
    ],
)
def test_validation_rejects_rule_breaking_plans(bad):
    with pytest.raises(PlanError):
        validate_plan(situation(), bad)


def test_validation_rejects_more_pumps_than_available():
    with pytest.raises(PlanError, match="pumps"):
        validate_plan(situation(pumps=1), [proposal(target="U1"), proposal(target="U2")])


def test_validation_rejects_a_second_alert_within_three_hours():
    busy = situation(actions=[queued("area_alert", "Al Barsha", "proposed", start=9)])
    with pytest.raises(PlanError, match="within"):
        validate_plan(busy, [proposal("area_alert", "Al Barsha", 10, GOOD_ALERT)])


def test_zero_lead_alert_is_allowed_once_the_district_is_already_flooded():
    flooded = situation(districts=[district(deepest_now=45.0)])
    now = Evidence(forecast_depth_cm=60, lead_hours=0, confidence=0.9)
    validate_plan(flooded, [proposal("area_alert", "Al Barsha", 10, GOOD_ALERT, now)])


def test_rule_planner_output_passes_validation_for_every_hour(small_world):
    session = Session(small_world, RulePlanner())
    for hour in range(config.HOURS):
        current = session.situation(hour)
        validate_plan(current, RulePlanner().plan(current))


# ---------------------------------------------------------------- LLM planner


def llm_reply(*actions: ProposedAction) -> str:
    return json.dumps({"actions": [a.model_dump() for a in actions]})


def test_llm_plan_is_used_when_it_is_valid():
    planner = LLMPlanner(lambda system, user: llm_reply(proposal("close_underpass", "U1", 12)))
    name, reason, actions = run_planner(planner, situation())
    assert (name, reason) == ("llm", None)
    assert [(a.type, a.target) for a in actions] == [("close_underpass", "U1")]


def test_llm_is_given_the_situation_the_schema_and_the_rules():
    seen = {}

    def complete(system: str, user: str) -> str:
        seen.update(system=system, user=user)
        return llm_reply()

    run_planner(LLMPlanner(complete), situation())
    assert json.loads(seen["user"])["sites"][0]["target"] == "U1"
    assert '"start_hour"' in seen["system"] and "never a road or route" in seen["system"]


@pytest.mark.parametrize(
    "reply",
    [
        "I think you should close the underpass.",  # not JSON
        '{"actions": [{"type": "evacuate_city"}]}',  # wrong schema
        llm_reply(proposal(target="U404")),  # valid schema, breaks a hard rule
        llm_reply(*[proposal(target=t) for t in ("U1", "U2")]) ,  # fine alone...
    ],
)
def test_bad_llm_output_falls_back_to_the_rule_planner(reply, caplog):
    scarce = situation(pumps=1)  # ...but two pumps exceed the one available
    name, reason, actions = run_planner(LLMPlanner(lambda system, user: reply), scarce)
    assert name == "rules" and reason
    assert actions == RulePlanner().plan(scarce)
    assert "using RulePlanner" in caplog.text


def test_llm_network_failure_falls_back_to_the_rule_planner():
    def offline(system: str, user: str) -> str:
        raise ConnectionError("no route to host")

    name, reason, actions = run_planner(LLMPlanner(offline), situation())
    assert name == "rules" and "ConnectionError" in reason and actions


# ---------------------------------------------------------------- approval gate


def frames(session: Session) -> list[bytes]:
    return [array.tobytes() for array in vars(session.timeline).values()]


def queue(session: Session, kind: str, start: int, message: str | None = None) -> Action:
    target = "Al Barsha" if kind == "area_alert" else UNDERPASS
    return session._queue(proposal(kind, target, start, message), hour=10)


def test_nothing_takes_effect_without_approval(small_world):
    session = Session(small_world, RulePlanner())
    baseline = frames(session)

    session.plan(10)
    pump = queue(session, "stage_pump", 11)
    closure = queue(session, "close_underpass", 11)
    alert = queue(session, "area_alert", 10, GOOD_ALERT)
    assert {a.status for a in session.actions} == {"proposed"}

    def untouched() -> bool:
        return (
            frames(session) == baseline
            and all(session.closed_segments(h) == [] for h in range(config.HOURS))
            and session.alerts(23) == []
            and pump_drainage(small_world.scenario, session.sites, session.actions) is None
            and session.situation(12).inventory.pumps_available == config.PUMP_COUNT
        )

    assert untouched()  # proposed only
    for action in (pump, closure, alert):
        session.decide(action.id, approve=False)
    assert untouched()  # rejected changes nothing either


def test_approved_pump_changes_the_simulation_from_its_start_hour_only(small_world):
    session = Session(small_world, RulePlanner())
    before = session.timeline.segment_cm.copy()
    pump = queue(session, "stage_pump", 11)
    session.decide(pump.id, approve=True)

    after = session.timeline.segment_cm
    members = session.sites.segments(UNDERPASS)
    assert np.array_equal(after[:11], before[:11])  # the past is untouched
    assert (after[11:, members] <= before[11:, members]).all()
    assert (after[11:, members] < before[11:, members]).any()  # the pump lowers the water
    assert session.situation(12).inventory.pumps_available == config.PUMP_COUNT - 1


def test_pump_adds_exactly_one_pump_of_drainage_and_only_when_approved(small_world):
    session = Session(small_world, RulePlanner())
    pump = queue(session, "stage_pump", 11)
    assert pump_drainage(small_world.scenario, session.sites, session.actions) is None
    session.decide(pump.id, approve=True)
    extra = pump_drainage(small_world.scenario, session.sites, session.actions)
    assert not extra[:11].any()
    assert np.isclose(extra[11].sum(), config.PUMP_DRAINAGE_CM_PER_HOUR)


def test_approved_closure_is_in_force_from_its_start_until_reopened(small_world):
    session = Session(small_world, RulePlanner())
    closure = queue(session, "close_underpass", 11)
    session.decide(closure.id, approve=True)
    members = sorted(int(s) for s in session.sites.segments(UNDERPASS))
    assert session.closed_segments(10) == []
    assert session.closed_segments(11) == members and session.closed_segments(20) == members

    reopen = queue(session, "open_road", 15)
    assert session.closed_segments(20) == members  # proposing a reopening does nothing
    session.decide(reopen.id, approve=True)
    assert session.closed_segments(14) == members and session.closed_segments(15) == []


def test_alert_reaches_the_in_app_channel_only_after_approval(small_world):
    session = Session(small_world, RulePlanner())
    alert = queue(session, "area_alert", 10, GOOD_ALERT)
    assert session.alerts(23) == []
    session.decide(alert.id, approve=True)
    assert [a.message for a in session.alerts(10)] == [GOOD_ALERT]
    assert session.alerts(9) == []  # not shown before it was issued


def test_decisions_are_final_and_checked(small_world):
    session = Session(small_world, RulePlanner())
    pump = queue(session, "stage_pump", 11)
    session.decide(pump.id, approve=False)
    with pytest.raises(ActionError, match="already rejected"):
        session.decide(pump.id, approve=True)
    with pytest.raises(ActionError, match="no action"):
        session.decide("A999", approve=True)


def test_cannot_approve_more_pumps_than_exist(small_world, monkeypatch):
    monkeypatch.setattr(config, "PUMP_COUNT", 1)
    session = Session(small_world, RulePlanner())
    first, second = queue(session, "stage_pump", 11), queue(session, "stage_pump", 12)
    session.decide(first.id, approve=True)
    with pytest.raises(ActionError, match="no pumps"):
        session.decide(second.id, approve=True)
    assert second.status == "proposed"


def test_reset_clears_the_queue_and_restores_the_baseline(small_world):
    session = Session(small_world, RulePlanner())
    baseline = frames(session)
    for kind, start, text in (("stage_pump", 11, None), ("area_alert", 10, GOOD_ALERT)):
        session.decide(queue(session, kind, start, text).id, approve=True)
    assert frames(session) != baseline
    session.reset()
    assert session.actions == [] and session.alerts(23) == [] and frames(session) == baseline


def test_sites_group_road_pieces_and_label_them(small_world):
    sites = build_sites(small_world.scenario)
    assert UNDERPASS in sites.targets and "R1000" in sites.targets
    position = sites.position(UNDERPASS)
    assert sites.underpass[position] and "underpass" in sites.labels[position]


def test_carriageways_of_one_underpass_are_a_single_site():
    cells = [np.array([1, 2]), np.array([2, 3]), np.array([9]), np.array([3, 4])]
    way_ids = np.array([50, 40, 60, 70])
    underpass = np.array([True, True, True, False])
    keys = underpass_groups(way_ids, underpass, cells)
    # ways 50 and 40 share cell 2 -> one site; 60 is elsewhere; 70 is a surface road
    assert list(keys) == [40, 40, 60, 70]


def test_several_pump_approvals_cost_one_rebuild(small_world, monkeypatch):
    import app.city as city

    calls = []
    real = city.build_timeline
    monkeypatch.setattr(city, "build_timeline", lambda *a: calls.append(1) or real(*a))
    session = Session(small_world, RulePlanner())
    monkeypatch.setattr(config, "PUMP_COUNT", 5)
    for start in (11, 12, 13):
        session.decide(queue(session, "stage_pump", start).id, approve=True)
    assert calls == []  # nothing rebuilt yet
    session.timeline
    session.timeline
    assert calls == [1]


# ---------------------------------------------------------------- API


@pytest.fixture()
def client(small_world):
    with TestClient(create_app(small_world, RulePlanner())) as test_client:
        yield test_client


def test_api_plan_queues_proposals_without_changing_the_replay(client):
    before = client.get("/api/replay/12").json()
    result = client.post("/api/plan/10").json()
    assert result["planner"] == "rules" and result["fallback_reason"] is None
    assert all(a["status"] == "proposed" for a in result["actions"])
    after = client.get("/api/replay/12").json()
    assert after["actions"] == result["actions"]
    for key in ("risk", "risk_next_6h", "sensors", "closed_segments", "alerts",
                "pumps_available"):
        assert after[key] == before[key], key


def test_api_approve_reject_and_reset(client):
    actions = client.post("/api/plan/10").json()["actions"]
    assert actions, "the synthetic storm should give the rule planner something to propose"
    first = actions[0]["id"]
    assert client.post(f"/api/actions/{first}/approve").json()["status"] == "approved"
    assert client.post(f"/api/actions/{first}/approve").status_code == 409
    assert client.post(f"/api/actions/{first}/reject").status_code == 409
    assert client.post("/api/actions/A999/reject").status_code == 409
    assert client.post("/api/reset").json() == {"ok": True}
    assert client.get("/api/replay/10").json()["actions"] == []


def test_api_records_an_operator_decision(client):
    action = client.post("/api/plan/10").json()["actions"][0]
    assert action["decided_by"] is None  # proposed: nobody has decided yet
    approved = client.post(f"/api/actions/{action['id']}/approve").json()
    assert (approved["status"], approved["decided_by"]) == ("approved", "operator")


def test_api_labels_a_demo_mode_approval(client):
    first = client.post("/api/plan/10").json()["actions"][0]["id"]
    auto = client.post(f"/api/actions/{first}/approve?by=demo_auto").json()
    assert (auto["status"], auto["decided_by"]) == ("approved", "demo_auto")
    assert client.get("/api/replay/10").json()["actions"][0]["decided_by"] == "demo_auto"


def test_api_rejects_an_unknown_decider(client):
    first = client.post("/api/plan/10").json()["actions"][0]["id"]
    assert client.post(f"/api/actions/{first}/approve?by=agent").status_code == 422
    assert client.get("/api/replay/10").json()["actions"][0]["status"] == "proposed"


def test_api_plan_rejects_hours_outside_the_day(client):
    assert client.post("/api/plan/24").status_code == 404
