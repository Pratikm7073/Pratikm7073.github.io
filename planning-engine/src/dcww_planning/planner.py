"""End-to-end plan construction: forecast, requirement, supply, gap, cost.

This is the module that turns the pieces into something a Planning &
Performance team would actually take to a review. It answers, week by
week across the horizon:

* how many contacts are coming, by queue and channel;
* how many advisors that needs on the phone, and rostered;
* how many advisors will actually be available, given attrition and the
  recruitment pipeline;
* what the gap is, what it costs to close, and what it costs not to.

**Scenarios are re-computed, not scaled.** It is tempting to answer "what
if volume is 10% higher" by multiplying the FTE requirement by 1.1. That
is wrong, and wrong in a direction that matters: Erlang is non-linear, so
larger queues pool their variance better and +10% volume needs materially
less than +10% headcount. Every scenario re-runs the full interval
sizing, and the sub-linearity it reveals is one of the more useful things
a planner can put in front of an operations director.

Volume and AHT scale almost identically, because both enter the queueing
calculation only through offered load (contacts x AHT). AHT is very
slightly the worse of the two - it also lengthens the wait for a given
number of free agents - but the difference is a fraction of a per cent,
not the large gap the folklore claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .backtest import SelectionResult
from .capacity import (
    INTERVALS_PER_DAY, IntervalPlan, SupplyWeek, build_interval_plan,
    cover_day, recruitment_plan, supply_plan,
)
from .config import INTERVAL_MINUTES, PlanConfig
from .models import MODEL_REGISTRY

__all__ = ["PlanResult", "build_plan", "profile_lookup", "run_scenarios", "SCENARIOS"]

MAX_OVERTIME_SHARE = 0.08      # of contracted hours, before agency is needed
MAX_AGENCY_SHARE = 0.12        # realistic ceiling on agency cover


def profile_lookup(profiles: pd.DataFrame) -> dict[str, dict[int, np.ndarray]]:
    """Index the interval profile table as line -> weekday -> shares."""
    nested: dict[str, dict[int, np.ndarray]] = {}
    for row in profiles.itertuples():
        by_day = nested.setdefault(row.line_key, {})
        arr = by_day.get(row.weekday)
        if arr is None:
            arr = np.zeros(INTERVALS_PER_DAY)
            by_day[row.weekday] = arr
        arr[row.interval] = row.share
    return nested


@dataclass
class PlanResult:
    """Everything the plan produces, ready for export."""

    config: PlanConfig
    start: date
    horizon_days: int
    forecast: pd.DataFrame
    daily_line: pd.DataFrame
    weekly: pd.DataFrame
    intervals: pd.DataFrame
    supply: list[SupplyWeek]
    intake: dict[int, int]
    rosters: dict[date, object] = field(default_factory=dict)
    selection: dict[str, SelectionResult] = field(default_factory=dict)
    scenarios: pd.DataFrame | None = None
    risks: list = field(default_factory=list)

    @property
    def end(self) -> date:
        return self.start + timedelta(days=self.horizon_days - 1)

    def headline(self) -> dict:
        w = self.weekly
        return {
            "horizon_start": self.start,
            "horizon_end": self.end,
            "weeks": len(w),
            "total_contacts": float(w["contacts"].sum()),
            "peak_week": w.loc[w["required_fte"].idxmax(), "week_start"],
            "peak_required_fte": float(w["required_fte"].max()),
            "mean_required_fte": float(w["required_fte"].mean()),
            "worst_gap_fte": float(w["gap_fte"].min()),
            "weeks_short": int((w["gap_fte"] < -0.5).sum()),
            "total_cost": float(w["total_cost"].sum()),
            "premium_cost": float(w["overtime_cost"].sum() + w["agency_cost"].sum()),
            "unmet_fte_weeks": float(w["unmet_fte"].sum()),
            "idle_fte_weeks": float(w["idle_hours"].sum() / self.config.cost.contracted_hours_per_week),
        }


def build_plan(
    config: PlanConfig,
    daily_history: pd.DataFrame,
    profiles: pd.DataFrame,
    horizon_days: int = 182,
    selection: dict[str, SelectionResult] | None = None,
    default_model: str = "ridge_log",
    interval_sample_days: int = 14,
    roster_days: int = 7,
    volume_multiplier: float = 1.0,
    aht_multiplier: float = 1.0,
    shrinkage_override: float | None = None,
    attrition_multiplier: float = 1.0,
    forecast_cache: dict[str, pd.DataFrame] | None = None,
) -> PlanResult:
    """Build a complete resource plan over `horizon_days`.

    The multiplier arguments exist so scenarios re-enter this same
    function rather than approximating around its output - the scenario
    and the base plan are then guaranteed to be computed identically.

    `forecast_cache` lets a scenario reuse the base forecast rather than
    re-fitting sixteen models for a question that only changes AHT. The
    forecast is a property of demand; AHT, shrinkage and attrition are
    not, so re-fitting for them would be waste.
    """
    profile_map = profile_lookup(profiles)
    last_history = max(daily_history["date"])
    start = last_history + timedelta(days=1)
    future_days = [start + timedelta(days=i) for i in range(horizon_days)]

    # ── 1. Forecast every service line ──
    if forecast_cache is not None and "forecast" in forecast_cache:
        forecast = forecast_cache["forecast"].copy()
    else:
        rows: list[dict] = []
        for line in config.service_lines:
            subset = daily_history[daily_history["line_key"] == line.key].sort_values("date")
            history_days = list(subset["date"])
            y = subset["offered"].to_numpy(dtype=float)
            model_name = default_model
            if selection and line.key in selection:
                model_name = selection[line.key].chosen
            result = MODEL_REGISTRY[model_name]().fit_predict(line, history_days, y, future_days)
            rows.extend(result.as_rows())
        forecast = pd.DataFrame(rows)
        if forecast_cache is not None:
            forecast_cache["forecast"] = forecast.copy()

    forecast = forecast.copy()
    forecast["forecast"] = forecast["forecast"] * volume_multiplier
    forecast["p10"] = forecast["p10"] * volume_multiplier
    forecast["p90"] = forecast["p90"] * volume_multiplier

    effective_config = config
    if shrinkage_override is not None:
        effective_config = _config_with_total_shrinkage(config, shrinkage_override)

    # ── 2. Size every day, every line ──
    daily_rows: list[dict] = []
    interval_rows: list[dict] = []
    day_requirement: dict[date, np.ndarray] = {}

    forecast_by_line = {k: v for k, v in forecast.groupby("line_key")}
    sample_cutoff = start + timedelta(days=interval_sample_days)

    for line in config.service_lines:
        channel = config.channel(line.channel)
        aht = channel.aht_seconds * line.aht_multiplier * aht_multiplier
        line_forecast = forecast_by_line.get(line.key)
        if line_forecast is None:
            continue
        volumes = dict(zip(line_forecast["date"], line_forecast["forecast"]))

        for day in future_days:
            contacts = float(volumes.get(day, 0.0))
            profile = profile_map.get(line.key, {}).get(day.weekday())
            if profile is None or contacts <= 0:
                continue

            plan = build_interval_plan(day, line, contacts, profile, effective_config, aht_seconds=aht)
            bucket = day_requirement.setdefault(day, np.zeros(INTERVALS_PER_DAY))
            bucket += plan.rostered_required

            daily_rows.append({
                "date": day,
                "line_key": line.key,
                "queue": line.queue,
                "channel": line.channel,
                "contacts": plan.total_contacts(),
                "workload_hours": float(plan.contacts.sum() * aht / 3600.0),
                "on_phone_hours": float(plan.on_phone_required.sum()) * (INTERVAL_MINUTES / 60.0),
                "rostered_hours": plan.rostered_hours(),
                "peak_rostered": plan.peak_rostered(),
                "mean_service_level": float(
                    np.mean(plan.service_level[plan.contacts > 0]) if (plan.contacts > 0).any() else 1.0
                ),
                "mean_occupancy": float(
                    np.mean(plan.occupancy[plan.contacts > 0]) if (plan.contacts > 0).any() else 0.0
                ),
            })

            if day < sample_cutoff:
                for i in np.nonzero(plan.contacts > 0)[0]:
                    interval_rows.append({
                        "date": day,
                        "interval": int(i),
                        "interval_start": f"{int(i) * INTERVAL_MINUTES // 60:02d}:{int(i) * INTERVAL_MINUTES % 60:02d}",
                        "line_key": line.key,
                        "channel": line.channel,
                        "contacts": round(float(plan.contacts[i]), 2),
                        "on_phone_required": round(float(plan.on_phone_required[i]), 2),
                        "rostered_required": round(float(plan.rostered_required[i]), 2),
                        "service_level": round(float(plan.service_level[i]), 4),
                        "occupancy": round(float(plan.occupancy[i]), 4),
                        "binding_constraint": plan.binding[i],
                    })

    daily_line = pd.DataFrame(daily_rows)
    intervals = pd.DataFrame(interval_rows)

    # ── 3. Roll up to weeks ──
    daily_line["week_start"] = [d - timedelta(days=d.weekday()) for d in daily_line["date"]]
    contracted = config.cost.contracted_hours_per_week

    weekly = (
        daily_line.groupby("week_start")
        .agg(
            contacts=("contacts", "sum"),
            workload_hours=("workload_hours", "sum"),
            on_phone_hours=("on_phone_hours", "sum"),
            rostered_hours=("rostered_hours", "sum"),
        )
        .reset_index()
        .sort_values("week_start")
        .reset_index(drop=True)
    )
    # FTE is required person-hours divided by the hours one FTE works.
    weekly["required_fte"] = weekly["rostered_hours"] / contracted
    weekly["on_phone_fte"] = weekly["on_phone_hours"] / contracted

    # ── 4. Supply, recruitment, gap ──
    supply_config = _config_with_attrition(config, attrition_multiplier)
    week_starts = list(weekly["week_start"])
    required = list(weekly["required_fte"])
    intake = recruitment_plan(supply_config, week_starts[0], required)
    supply = supply_plan(supply_config, week_starts[0], len(week_starts), intake)

    weekly["supply_fte"] = [s.productive_fte for s in supply]
    weekly["intake"] = [s.intake for s in supply]
    weekly["leavers"] = [round(s.leavers, 2) for s in supply]
    weekly["in_training"] = [round(s.in_training, 1) for s in supply]
    weekly["gap_fte"] = weekly["supply_fte"] - weekly["required_fte"]
    weekly["coverage_pct"] = weekly["supply_fte"] / weekly["required_fte"].replace(0, np.nan) * 100

    weekly = _apply_costs(weekly, config)

    # ── 5. Rosters for the first few days ──
    rosters = {}
    for day in future_days[:roster_days]:
        curve = day_requirement.get(day)
        if curve is not None and curve.sum() > 0:
            rosters[day] = cover_day(day, curve)

    return PlanResult(
        config=config, start=start, horizon_days=horizon_days,
        forecast=forecast, daily_line=daily_line, weekly=weekly,
        intervals=intervals, supply=supply, intake=intake,
        rosters=rosters, selection=selection or {},
    )


def _apply_costs(weekly: pd.DataFrame, config: PlanConfig) -> pd.DataFrame:
    """Price the plan, including the cost of getting it wrong either way.

    Under-staffing is closed with overtime first and agency after, because
    that is the order an operation actually reaches for them and they cost
    different amounts. Over-staffing is not free either: those hours are
    contracted and paid whether or not there is work, so they are reported
    as idle cost rather than netted off. A plan that shows only the
    shortfall makes over-recruitment look costless.
    """
    cost = config.cost
    contracted = cost.contracted_hours_per_week
    rate = cost.advisor_hourly_cost

    supply_hours = weekly["supply_fte"] * contracted
    required_hours = weekly["required_fte"] * contracted
    deficit_hours = (required_hours - supply_hours).clip(lower=0)
    surplus_hours = (supply_hours - required_hours).clip(lower=0)

    overtime_hours = np.minimum(deficit_hours, supply_hours * MAX_OVERTIME_SHARE)
    # Agency cover is capped. Treating it as infinitely available turns
    # every shortfall into a pure cost question and none into a service
    # question, which flatters exactly the wrong scenarios: higher
    # attrition then looks *cheaper*, because the salary saved on the
    # empty seats exceeds the premium on covering them. In reality there
    # is a limit to how many trained billing advisors an agency can supply
    # at short notice, and beyond it the contacts simply go unanswered.
    agency_hours = np.minimum(deficit_hours - overtime_hours, supply_hours * MAX_AGENCY_SHARE)
    unmet_hours = (deficit_hours - overtime_hours - agency_hours).clip(lower=0)

    weekly["base_cost"] = supply_hours * rate
    weekly["overtime_hours"] = overtime_hours
    weekly["overtime_cost"] = overtime_hours * rate * cost.overtime_multiplier
    weekly["agency_hours"] = agency_hours
    weekly["agency_cost"] = agency_hours * rate * cost.agency_multiplier
    weekly["unmet_hours"] = unmet_hours
    weekly["unmet_fte"] = unmet_hours / contracted
    weekly["idle_hours"] = surplus_hours
    weekly["idle_cost"] = surplus_hours * rate
    weekly["recruitment_cost"] = weekly["intake"] * cost.recruitment_cost_per_head
    weekly["total_cost"] = (
        weekly["base_cost"] + weekly["overtime_cost"]
        + weekly["agency_cost"] + weekly["recruitment_cost"]
    )
    return weekly


def _config_with_total_shrinkage(config: PlanConfig, total: float) -> PlanConfig:
    """Rescale every shrinkage component to hit a given total.

    Scaling the components rather than overriding the total keeps the
    build-up internally consistent, so the scenario still shows *where*
    the shrinkage sits rather than replacing it with an unexplained
    number.
    """
    from dataclasses import replace
    current = config.shrinkage.total
    if current <= 0 or total <= 0:
        return config
    factor = total / current
    scaled = {k: min(v * factor, 0.6) for k, v in vars(config.shrinkage).items()}
    return replace(config, shrinkage=replace(config.shrinkage, **scaled))


def _config_with_attrition(config: PlanConfig, multiplier: float) -> PlanConfig:
    from dataclasses import replace
    if multiplier == 1.0:
        return config
    annual = min(0.95, config.supply.annual_attrition * multiplier)
    return replace(config, supply=replace(config.supply, annual_attrition=annual))


# ─────────────────────────────────────────────────────────────────────
# Scenarios
# ─────────────────────────────────────────────────────────────────────

SCENARIOS: dict[str, dict] = {
    "base": {},
    "volume_up_10": {"volume_multiplier": 1.10},
    "volume_down_5": {"volume_multiplier": 0.95},
    "aht_up_5": {"aht_multiplier": 1.05},
    "shrinkage_up_3pt": {"shrinkage_delta": 0.03},
    "attrition_up_50": {"attrition_multiplier": 1.5},
    "digital_shift": {"volume_multiplier": 0.93, "aht_multiplier": 1.06},
}

SCENARIO_LABELS = {
    "base": "Base plan",
    "volume_up_10": "Contact volume +10%",
    "volume_down_5": "Contact volume -5%",
    "aht_up_5": "AHT +5%",
    "shrinkage_up_3pt": "Shrinkage +3 points",
    "attrition_up_50": "Attrition 1.5x",
    "digital_shift": "Digital deflection: -7% volume, +6% AHT",
}


def run_scenarios(
    config: PlanConfig,
    daily_history: pd.DataFrame,
    profiles: pd.DataFrame,
    horizon_days: int = 182,
    selection: dict[str, SelectionResult] | None = None,
    scenarios: dict[str, dict] | None = None,
) -> tuple[pd.DataFrame, dict[str, PlanResult]]:
    """Re-run the full plan under each scenario and tabulate the deltas.

    Note what the `digital_shift` scenario encodes, because it is the one
    planners most often get wrong: successful self-serve deflection
    removes the *simple* contacts. Volume falls, but what is left is
    harder, so AHT rises. Modelled as volume alone it looks like a pure
    saving; modelled honestly it is a much smaller one.
    """
    scenarios = scenarios or SCENARIOS
    cache: dict[str, pd.DataFrame] = {}
    results: dict[str, PlanResult] = {}
    rows: list[dict] = []

    for name, spec in scenarios.items():
        kwargs = dict(spec)
        delta = kwargs.pop("shrinkage_delta", None)
        if delta is not None:
            kwargs["shrinkage_override"] = config.shrinkage.total + delta

        plan = build_plan(
            config, daily_history, profiles,
            horizon_days=horizon_days, selection=selection,
            interval_sample_days=0, roster_days=0,
            forecast_cache=cache, **kwargs,
        )
        results[name] = plan
        head = plan.headline()
        rows.append({
            "scenario": name,
            "label": SCENARIO_LABELS.get(name, name),
            "peak_required_fte": round(head["peak_required_fte"], 1),
            "mean_required_fte": round(head["mean_required_fte"], 1),
            "weeks_short": head["weeks_short"],
            "worst_gap_fte": round(head["worst_gap_fte"], 1),
            "total_cost": round(head["total_cost"]),
            "premium_cost": round(head["premium_cost"]),
            "unmet_fte_weeks": round(head["unmet_fte_weeks"], 1),
            "idle_fte_weeks": round(head["idle_fte_weeks"], 1),
        })

    table = pd.DataFrame(rows)
    base_cost = float(table.loc[table["scenario"] == "base", "total_cost"].iloc[0])
    base_fte = float(table.loc[table["scenario"] == "base", "mean_required_fte"].iloc[0])
    table["cost_vs_base"] = (table["total_cost"] - base_cost).round()
    table["cost_vs_base_pct"] = ((table["total_cost"] / base_cost - 1) * 100).round(2)
    table["fte_vs_base"] = (table["mean_required_fte"] - base_fte).round(1)
    return table, results
