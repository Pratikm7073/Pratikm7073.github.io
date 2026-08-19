"""End-to-end plan construction, scenarios and the risk register."""

from datetime import timedelta

import numpy as np
import pytest

from dcww_planning.planner import build_plan, profile_lookup, run_scenarios
from dcww_planning.risk import build_risk_register, leave_reprofiling_opportunity

HORIZON = 84


@pytest.fixture(scope="module")
def plan(config, daily, profiles):
    return build_plan(config, daily, profiles, horizon_days=HORIZON)


def test_profile_lookup_shares_sum_to_one(profiles):
    lookup = profile_lookup(profiles)
    for line_key, by_weekday in lookup.items():
        for weekday, shares in by_weekday.items():
            assert shares.sum() == pytest.approx(1.0, abs=1e-3), (line_key, weekday)


def test_plan_starts_the_day_after_history_ends(plan, daily):
    assert plan.start == max(daily["date"]) + timedelta(days=1)
    assert plan.horizon_days == HORIZON


def test_weekly_totals_reconcile_to_the_daily_frame(plan):
    """The roll-up must not quietly lose or duplicate volume."""
    assert plan.weekly["contacts"].sum() == pytest.approx(
        plan.daily_line["contacts"].sum(), rel=1e-9)
    assert plan.weekly["rostered_hours"].sum() == pytest.approx(
        plan.daily_line["rostered_hours"].sum(), rel=1e-9)


def test_fte_is_hours_divided_by_contracted_hours(plan, config):
    contracted = config.cost.contracted_hours_per_week
    assert plan.weekly["required_fte"].to_numpy() == pytest.approx(
        (plan.weekly["rostered_hours"] / contracted).to_numpy())


def test_rostered_always_exceeds_on_phone(plan):
    """Shrinkage only ever grosses a requirement up."""
    assert (plan.weekly["required_fte"] >= plan.weekly["on_phone_fte"]).all()
    ratio = plan.weekly["required_fte"] / plan.weekly["on_phone_fte"]
    assert ratio.min() > 1.0


def test_gap_is_supply_minus_requirement(plan):
    assert plan.weekly["gap_fte"].to_numpy() == pytest.approx(
        (plan.weekly["supply_fte"] - plan.weekly["required_fte"]).to_numpy())


def test_costs_are_non_negative_and_add_up(plan):
    for column in ("base_cost", "overtime_cost", "agency_cost", "recruitment_cost", "total_cost"):
        assert (plan.weekly[column] >= 0).all(), column
    total = (plan.weekly["base_cost"] + plan.weekly["overtime_cost"]
             + plan.weekly["agency_cost"] + plan.weekly["recruitment_cost"])
    assert plan.weekly["total_cost"].to_numpy() == pytest.approx(total.to_numpy())


def test_premium_cover_only_appears_in_weeks_that_are_short(plan):
    covered = plan.weekly[plan.weekly["gap_fte"] > 0.5]
    assert (covered["overtime_hours"] == 0).all()
    assert (covered["agency_hours"] == 0).all()


def test_forecast_covers_the_whole_horizon(plan, config):
    days = set(plan.forecast["date"])
    assert len(days) == HORIZON
    assert set(plan.forecast["line_key"]) == {line.key for line in config.service_lines}


def test_rosters_cover_their_requirement(plan):
    assert plan.rosters
    for day, roster in plan.rosters.items():
        assert roster.under_cover_hours < 2.0
        assert 0.5 < roster.efficiency <= 1.0


def test_intervals_record_which_constraint_bound(plan):
    assert not plan.intervals.empty
    binding = set(plan.intervals["binding_constraint"])
    assert binding <= {"service_level", "occupancy", "workload", "none"}
    interactive = plan.intervals[plan.intervals["channel"].isin(["voice", "webchat"])]
    assert (interactive["occupancy"] <= 0.86).all()


# ── Scenarios ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def scenarios(config, daily, profiles):
    table, results = run_scenarios(
        config, daily, profiles, horizon_days=HORIZON,
        scenarios={"base": {}, "volume_up_10": {"volume_multiplier": 1.10},
                   "aht_up_5": {"aht_multiplier": 1.05}},
    )
    return table, results


def test_volume_increase_needs_less_than_proportional_headcount(scenarios):
    """The central non-linearity, and the reason scenarios are re-run.

    Erlang staffing grows roughly as load plus a term in the square root
    of load, so a larger queue pools its variance better. Scaling the FTE
    requirement by the volume multiplier - the intuitive shortcut - would
    over-state the requirement and buy people who are not needed.
    """
    table, _ = scenarios
    base = float(table.loc[table["scenario"] == "base", "mean_required_fte"].iloc[0])
    up = float(table.loc[table["scenario"] == "volume_up_10", "mean_required_fte"].iloc[0])
    growth = up / base - 1.0
    assert 0 < growth < 0.10, f"expected sub-linear growth, got {growth:.1%}"


def test_aht_and_volume_scale_almost_identically(scenarios):
    """Both enter the queue only through offered load (contacts x AHT).

    The folklore that AHT is dramatically worse than volume does not
    survive the arithmetic. AHT is very slightly worse, because it also
    lengthens the wait for a given number of free agents.
    """
    table, _ = scenarios
    base = float(table.loc[table["scenario"] == "base", "mean_required_fte"].iloc[0])
    aht = float(table.loc[table["scenario"] == "aht_up_5", "mean_required_fte"].iloc[0])
    volume = float(table.loc[table["scenario"] == "volume_up_10", "mean_required_fte"].iloc[0])
    aht_growth = aht / base - 1.0
    half_volume_growth = (volume / base - 1.0) / 2
    assert aht_growth == pytest.approx(half_volume_growth, abs=0.01)


def test_scenarios_report_against_the_base(scenarios):
    table, _ = scenarios
    base_row = table[table["scenario"] == "base"].iloc[0]
    assert base_row["cost_vs_base"] == 0
    assert base_row["fte_vs_base"] == 0


# ── Risk register ──────────────────────────────────────────────────────

def test_risk_register_separates_recoverable_from_unrecoverable(plan, config):
    risks = build_risk_register(plan, config)
    assert risks
    pipeline = (config.supply.recruitment_lead_weeks + config.supply.training_weeks
                + config.supply.nesting_weeks)
    for risk in risks:
        if risk.code.startswith("GAP-") and risk.week is not None:
            weeks_out = (risk.week - plan.start).days // 7
            assert risk.recoverable == (weeks_out >= pipeline)


def test_risks_are_sorted_by_severity(plan, config):
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    severities = [order[r.severity] for r in build_risk_register(plan, config)]
    assert severities == sorted(severities)


def test_every_risk_carries_a_mitigation(plan, config):
    for risk in build_risk_register(plan, config):
        assert risk.mitigation.strip()
        assert risk.detail.strip()


def test_welsh_language_risk_is_always_raised(plan, config):
    """A small statutory skill pool is a standing risk, not a seasonal one."""
    codes = {r.code for r in build_risk_register(plan, config)}
    assert "WELSH-SKILL-POOL" in codes


def test_leave_reprofiling_is_capped_by_entitlement(plan, config):
    """Only leave can be moved, not the whole surplus."""
    movable, saving, troughs, peaks = leave_reprofiling_opportunity(plan.weekly, config)
    assert movable >= 0
    surplus = plan.weekly[plan.weekly["gap_fte"] > 0]
    if not surplus.empty:
        ceiling = float((surplus["required_fte"] * config.shrinkage.annual_leave).sum())
        assert movable <= ceiling + 1e-6
    if movable > 0:
        assert saving > 0
        assert troughs and peaks
