"""Export a compact JSON payload for the interactive browser demo.

The demo recomputes Erlang, shrinkage and cost *client side* so its
sliders respond instantly, which means this payload has to carry the
inputs to that calculation rather than just its results: interval-level
contact volumes, channel parameters, the shrinkage build-up and the cost
model. Shipping only the finished FTE numbers would leave the browser
with nothing to recompute and reduce the demo to a picture.

Size discipline matters - this is served from GitHub Pages. Interval
detail is limited to one representative week and everything is rounded
at export, which keeps the payload comfortably under a megabyte.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .config import INTERVALS_PER_DAY, PlanConfig

__all__ = ["build_payload", "write_payload"]


def _clean(value):
    """Make numpy/pandas/date values JSON-safe."""
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if np.isnan(value) else round(float(value), 4)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if isinstance(value, (date,)):
        return value.isoformat()
    if isinstance(value, float):
        return None if np.isnan(value) else round(value, 4)
    return value


def _records(frame: pd.DataFrame) -> list[dict]:
    return [{k: _clean(v) for k, v in row.items()} for row in frame.to_dict("records")]


def build_payload(
    plan,
    config: PlanConfig,
    history: pd.DataFrame,
    risks: list | None = None,
    scenarios: pd.DataFrame | None = None,
    history_weeks: int = 78,
) -> dict:
    head = plan.headline()

    # ── Channel and cost parameters for client-side recompute ──
    channels = [{
        "key": c.key, "label": c.label, "kind": c.kind,
        "aht": c.aht_seconds, "concurrency": c.concurrency,
        "slTarget": c.service_level_target, "slSeconds": c.service_level_seconds,
        "slaHours": c.sla_hours, "maxOccupancy": c.max_occupancy,
        "patience": c.patience_seconds, "utilisation": c.productive_utilisation,
    } for c in config.channels]

    # ── Weekly headline series ──
    weekly = plan.weekly[[
        "week_start", "contacts", "workload_hours", "on_phone_fte", "required_fte",
        "supply_fte", "gap_fte", "intake", "overtime_hours", "agency_hours",
        "idle_hours", "total_cost",
    ]].copy()

    # ── History vs forecast, aggregated to weeks for the headline chart ──
    hist = history.copy()
    hist["week_start"] = [d - timedelta(days=d.weekday()) for d in hist["date"]]
    hist_weekly = (
        hist.groupby(["week_start", "channel"])["offered"].sum().reset_index()
        .rename(columns={"offered": "contacts"})
    )
    cutoff = max(hist_weekly["week_start"]) - timedelta(weeks=history_weeks)
    hist_weekly = hist_weekly[hist_weekly["week_start"] >= cutoff]

    fc = plan.forecast.merge(
        pd.DataFrame([{"line_key": l.key, "channel": l.channel} for l in config.service_lines]),
        on="line_key", how="left",
    )
    fc["week_start"] = [d - timedelta(days=d.weekday()) for d in fc["date"]]
    fc_weekly = fc.groupby(["week_start", "channel"])["forecast"].sum().reset_index()

    # ── One representative week of interval detail ──
    intraday = []
    if not plan.intervals.empty:
        sample_day = _busiest_weekday(plan.intervals)
        day_slice = plan.intervals[plan.intervals["date"] == sample_day]
        for line in config.service_lines:
            rows = day_slice[day_slice["line_key"] == line.key]
            if rows.empty:
                continue
            contacts = np.zeros(INTERVALS_PER_DAY)
            for r in rows.itertuples():
                contacts[r.interval] = r.contacts
            intraday.append({
                "lineKey": line.key,
                "label": line.label,
                "queue": line.queue,
                "channel": line.channel,
                "ahtSeconds": round(config.channel(line.channel).aht_seconds * line.aht_multiplier, 1),
                "welsh": line.welsh_language,
                "contacts": [round(float(v), 2) for v in contacts],
            })
    else:
        sample_day = plan.start

    # ── Backtest comparison ──
    accuracy = []
    for key, sel in plan.selection.items():
        by_horizon = {}
        for acc in sel.accuracy:
            by_horizon.setdefault(acc.horizon, {})[acc.model] = {
                "wape": round(acc.wape, 2), "mape": round(acc.mape, 2),
                "bias": round(acc.bias_pct, 2),
            }
        line = config.line(key)
        accuracy.append({
            "lineKey": key, "label": line.label, "queue": line.queue, "channel": line.channel,
            "chosen": sel.chosen,
            "baselineWape": round(sel.baseline_wape, 2),
            "chosenWape": round(sel.chosen_wape, 2),
            "improvementPct": round(sel.improvement_pct, 1),
            "byHorizon": by_horizon,
        })

    payload = {
        "meta": {
            "title": "Retail Resource Planning & Forecast Engine",
            "organisation": config.name,
            "generated": date.today().isoformat(),
            "horizonStart": head["horizon_start"].isoformat(),
            "horizonEnd": head["horizon_end"].isoformat(),
            "weeks": head["weeks"],
            "sampleDay": sample_day.isoformat() if hasattr(sample_day, "isoformat") else str(sample_day),
            "dataNote": "All figures are generated from a synthetic dataset. No Welsh Water data is used.",
        },
        "config": {
            "channels": channels,
            "shrinkage": {
                "components": {k: round(v, 5) for k, v in config.shrinkage.components().items()},
                "regular": round(config.shrinkage.regular, 5),
                "irregular": round(config.shrinkage.irregular, 5),
                "total": round(config.shrinkage.total, 5),
                "upliftFactor": round(config.shrinkage.uplift_factor, 5),
            },
            "cost": {
                "hourly": config.cost.advisor_hourly_cost,
                "overtimeMultiplier": config.cost.overtime_multiplier,
                "agencyMultiplier": config.cost.agency_multiplier,
                "contractedHours": config.cost.contracted_hours_per_week,
                "recruitmentPerHead": config.cost.recruitment_cost_per_head,
            },
            "supply": {
                "openingFte": config.supply.opening_fte,
                "annualAttrition": config.supply.annual_attrition,
                "trainingWeeks": config.supply.training_weeks,
                "nestingWeeks": config.supply.nesting_weeks,
                "nestingProductivity": config.supply.nesting_productivity,
                "leadWeeks": config.supply.recruitment_lead_weeks,
                "pipelineWeeks": (config.supply.recruitment_lead_weeks
                                  + config.supply.training_weeks + config.supply.nesting_weeks),
                "maxIntakePerMonth": config.supply.max_intake_per_month,
            },
        },
        "headline": {k: _clean(v) for k, v in head.items()},
        "weekly": _records(weekly),
        "history": _records(hist_weekly),
        "forecastWeekly": _records(fc_weekly),
        "intraday": intraday,
        "accuracy": accuracy,
        "supply": [{k: _clean(v) for k, v in s.as_row().items()} for s in plan.supply],
        "scenarios": _records(scenarios) if scenarios is not None else [],
        "risks": [{k: _clean(v) for k, v in r.as_row().items()} for r in (risks or [])],
    }
    return payload


def _busiest_weekday(intervals: pd.DataFrame):
    """Pick the sample day with the most contacts, excluding weekends."""
    weekday_only = intervals[[d.weekday() < 5 for d in intervals["date"]]]
    frame = weekday_only if not weekday_only.empty else intervals
    totals = frame.groupby("date")["contacts"].sum()
    return totals.idxmax()


def write_payload(payload: dict, path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    return path
