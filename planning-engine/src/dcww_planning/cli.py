"""Command line interface.

    python -m dcww_planning generate     # write the synthetic dataset
    python -m dcww_planning backtest     # rolling-origin accuracy + model selection
    python -m dcww_planning plan         # build the plan, export the Excel pack
    python -m dcww_planning rta          # in-day analysis for one day
    python -m dcww_planning web          # JSON payload for the browser demo
    python -m dcww_planning all          # everything, in order

Backtesting is the slow step, so its result is cached to JSON and reused
by `plan` unless `--refresh` is passed. Re-running a twenty-seven second
model selection to re-export a spreadsheet is the kind of friction that
stops a tool being used daily.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from .backtest import select_models
from .config import INTERVALS_PER_DAY, default_config
from .excelpack import export_planning_pack
from .planner import build_plan, profile_lookup, run_scenarios
from .risk import build_risk_register
from .rta import recommend_actions, reforecast_intraday, schedule_adherence
from .synth import generate_history
from .webexport import build_payload, write_payload

DATA = Path("data")
OUT = Path("out")
SELECTION_CACHE = OUT / "model_selection.json"


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────

def _log(message: str) -> None:
    print(f"  {message}", flush=True)


def _load_history(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Read the generated dataset, regenerating it if absent."""
    daily_path = data_dir / "contacts_daily.csv"
    if not daily_path.exists():
        _log("no dataset found - generating one")
        return _generate(data_dir)

    daily = pd.read_csv(daily_path, parse_dates=["date"])
    daily["date"] = [d.date() for d in daily["date"]]
    profiles = pd.read_csv(data_dir / "interval_profiles.csv")
    interval = pd.read_csv(data_dir / "contacts_interval.csv", parse_dates=["date"])
    interval["date"] = [d.date() for d in interval["date"]]
    return daily, profiles, interval


def _generate(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    data_dir.mkdir(parents=True, exist_ok=True)
    result = generate_history()
    result.daily.to_csv(data_dir / "contacts_daily.csv", index=False)
    result.profiles.to_csv(data_dir / "interval_profiles.csv", index=False)
    result.interval.to_csv(data_dir / "contacts_interval.csv", index=False)
    return result.daily, result.profiles, result.interval


def _load_selection(config, daily, refresh: bool):
    """Model selection, cached because the backtest is the slow step."""
    if not refresh and SELECTION_CACHE.exists():
        cached = json.loads(SELECTION_CACHE.read_text())
        _log(f"reusing cached model selection ({len(cached)} lines) - pass --refresh to re-run")
        from .backtest import Accuracy, SelectionResult
        return {
            key: SelectionResult(
                line_key=key, chosen=v["chosen"],
                baseline_wape=v["baseline_wape"], chosen_wape=v["chosen_wape"],
                improvement_pct=v["improvement_pct"],
                accuracy=[Accuracy(**a) for a in v["accuracy"]],
                ensemble_weights=v["ensemble_weights"],
            )
            for key, v in cached.items()
        }

    _log("running rolling-origin backtest across all service lines")
    started = time.time()
    selection = select_models(config, daily)
    _log(f"backtest complete in {time.time() - started:.0f}s")

    OUT.mkdir(parents=True, exist_ok=True)
    SELECTION_CACHE.write_text(json.dumps({
        key: {
            "chosen": s.chosen, "baseline_wape": s.baseline_wape,
            "chosen_wape": s.chosen_wape, "improvement_pct": s.improvement_pct,
            "ensemble_weights": s.ensemble_weights,
            "accuracy": [vars(a) for a in s.accuracy],
        }
        for key, s in selection.items()
    }, indent=1))
    return selection


# ─────────────────────────────────────────────────────────────────────
# Commands
# ─────────────────────────────────────────────────────────────────────

def cmd_generate(args) -> int:
    daily, profiles, interval = _generate(Path(args.data))
    _log(f"contacts_daily.csv     {len(daily):>7,} rows  "
         f"({min(daily['date'])} to {max(daily['date'])})")
    _log(f"interval_profiles.csv  {len(profiles):>7,} rows")
    _log(f"contacts_interval.csv  {len(interval):>7,} rows")
    return 0


def cmd_backtest(args) -> int:
    config = default_config()
    daily, _, _ = _load_history(Path(args.data))
    selection = _load_selection(config, daily, refresh=True)

    rows = []
    for key, s in selection.items():
        rows.append({
            "line_key": key, "chosen_model": s.chosen,
            "baseline_wape": round(s.baseline_wape, 2),
            "chosen_wape": round(s.chosen_wape, 2),
            "improvement_pct": round(s.improvement_pct, 1),
            "beats_baseline": s.beats_baseline,
        })
    summary = pd.DataFrame(rows).sort_values("improvement_pct", ascending=False)
    OUT.mkdir(parents=True, exist_ok=True)
    summary.to_csv(OUT / "backtest_summary.csv", index=False)

    detail = pd.DataFrame([a.as_row() for s in selection.values() for a in s.accuracy])
    detail.to_csv(OUT / "backtest_detail.csv", index=False)

    print()
    print(summary.to_string(index=False))
    print()
    _log(f"mean error reduction against the naive baseline: {summary['improvement_pct'].mean():.1f}%")
    _log(f"written to {OUT / 'backtest_summary.csv'} and {OUT / 'backtest_detail.csv'}")
    return 0


def cmd_plan(args) -> int:
    config = default_config()
    daily, profiles, _ = _load_history(Path(args.data))
    selection = _load_selection(config, daily, refresh=args.refresh)

    _log(f"building a {args.horizon}-day plan")
    started = time.time()
    plan = build_plan(config, daily, profiles, horizon_days=args.horizon, selection=selection)
    _log(f"plan built in {time.time() - started:.0f}s")

    risks = build_risk_register(plan, config)
    _log(f"risk register: {len(risks)} entries "
         f"({sum(1 for r in risks if r.severity in ('critical', 'high'))} critical or high)")

    scenarios = None
    if not args.no_scenarios:
        _log("running scenarios (each re-runs the full interval sizing)")
        started = time.time()
        scenarios, _ = run_scenarios(config, daily, profiles,
                                     horizon_days=args.horizon, selection=selection)
        _log(f"scenarios complete in {time.time() - started:.0f}s")

    OUT.mkdir(parents=True, exist_ok=True)
    plan.weekly.to_csv(OUT / "weekly_plan.csv", index=False)
    plan.forecast.to_csv(OUT / "daily_forecast.csv", index=False)
    plan.intervals.to_csv(OUT / "interval_requirement.csv", index=False)
    pd.DataFrame([r.as_row() for r in risks]).to_csv(OUT / "risk_register.csv", index=False)
    if scenarios is not None:
        scenarios.to_csv(OUT / "scenarios.csv", index=False)

    pack = export_planning_pack(plan, config, OUT / "retail_planning_pack.xlsx",
                                risks=risks, scenarios=scenarios)

    head = plan.headline()
    print()
    print(f"  Horizon            {head['horizon_start']:%d %b %Y} to {head['horizon_end']:%d %b %Y} "
          f"({head['weeks']} weeks)")
    print(f"  Contacts forecast  {head['total_contacts']:>14,.0f}")
    print(f"  Mean FTE required  {head['mean_required_fte']:>14,.1f}")
    print(f"  Peak FTE required  {head['peak_required_fte']:>14,.1f}   (w/c {head['peak_week']:%d %b %Y})")
    print(f"  Weeks below cover  {head['weeks_short']:>14d}")
    print(f"  Worst weekly gap   {head['worst_gap_fte']:>14,.1f} FTE")
    print(f"  Unmet FTE-weeks    {head['unmet_fte_weeks']:>14,.1f}   (beyond overtime and agency capacity)")
    print(f"  Idle FTE-weeks     {head['idle_fte_weeks']:>14,.1f}   (paid capacity with no demand against it)")
    print(f"  Total cost         {head['total_cost']:>14,.0f} GBP")
    print(f"  Premium cost       {head['premium_cost']:>14,.0f} GBP  (overtime + agency)")
    print()
    if scenarios is not None:
        print(scenarios[["label", "mean_required_fte", "fte_vs_base", "weeks_short",
                         "unmet_fte_weeks", "idle_fte_weeks", "premium_cost",
                         "total_cost", "cost_vs_base_pct"]].to_string(index=False))
        print()
    _log(f"planning pack written to {pack}")
    return 0


def cmd_rta(args) -> int:
    config = default_config()
    daily, profiles, interval = _load_history(Path(args.data))
    lookup = profile_lookup(profiles)

    if args.date:
        target = datetime.strptime(args.date, "%Y-%m-%d").date()
    else:
        trading = [d for d in sorted(set(interval["date"])) if d.weekday() < 5]
        if not trading:
            _log("no trading days in the interval dataset")
            return 1
        target = trading[-1]

    day_slice = interval[interval["date"] == target]
    if day_slice.empty:
        _log(f"no interval data for {target}")
        return 1

    _log(f"in-day analysis for {target:%A %d %B %Y}, position taken at {args.elapsed_time}")
    elapsed = _interval_index(args.elapsed_time)

    rows, action_rows = [], []
    for line in config.service_lines:
        rows_for_line = day_slice[day_slice["line_key"] == line.key]
        if rows_for_line.empty:
            continue
        profile = lookup.get(line.key, {}).get(target.weekday())
        if profile is None:
            continue

        actuals = np.zeros(INTERVALS_PER_DAY)
        scheduled = np.zeros(INTERVALS_PER_DAY)
        staffed = np.zeros(INTERVALS_PER_DAY)
        for r in rows_for_line.itertuples():
            actuals[r.interval] = r.offered
            scheduled[r.interval] = r.scheduled
            staffed[r.interval] = r.staffed_actual

        # The "forecast" for the day is reconstructed from history so the
        # demo has something to have been wrong about.
        history = daily[(daily["line_key"] == line.key) & (daily["date"] < target)]
        same_weekday = history[[d.weekday() == target.weekday() for d in history["date"]]]
        day_forecast = float(same_weekday["offered"].tail(4).median()) if len(same_weekday) else float(actuals.sum())

        position = reforecast_intraday(target, line.key, profile, day_forecast, actuals, elapsed)
        adherence = schedule_adherence(scheduled, staffed)

        rows.append({
            "line_key": line.key, "channel": line.channel,
            "forecast": round(position.original_day_forecast, 1),
            "actual_so_far": round(position.actual_so_far, 1),
            "variance_pct": round(position.variance_pct, 1),
            "revised_forecast": round(position.revised_day_forecast, 1),
            "revision_pct": round(position.revision_pct, 1),
            "damping": round(position.damping_applied, 2),
            "adherence_pct": round(adherence.adherence_pct, 1),
            "conformance_pct": round(adherence.conformance_pct, 1),
            "understaffed_hours": round(adherence.understaffed_hours, 1),
        })

        channel = config.channel(line.channel)
        if channel.kind == "interactive":
            aht = channel.aht_seconds * line.aht_multiplier
            for action in recommend_actions(actuals, staffed, channel, aht, from_interval=elapsed):
                action["line_key"] = line.key
                action_rows.append(action)

    report = pd.DataFrame(rows)
    actions = pd.DataFrame(action_rows)
    OUT.mkdir(parents=True, exist_ok=True)
    report.to_csv(OUT / "rta_position.csv", index=False)
    actions.to_csv(OUT / "rta_actions.csv", index=False)

    print()
    print(report.to_string(index=False))
    print()
    if not actions.empty:
        top = actions.sort_values("deficit_fte", ascending=False).head(10)
        print("  Largest in-day gaps remaining:")
        print(top[["line_key", "interval_start", "contacts", "staffed",
                   "required", "deficit_fte", "recommended_action"]].to_string(index=False))
        print()
    _log(f"written to {OUT / 'rta_position.csv'} and {OUT / 'rta_actions.csv'}")
    return 0


def cmd_web(args) -> int:
    config = default_config()
    daily, profiles, _ = _load_history(Path(args.data))
    selection = _load_selection(config, daily, refresh=args.refresh)

    plan = build_plan(config, daily, profiles, horizon_days=args.horizon, selection=selection)
    risks = build_risk_register(plan, config)
    scenarios, _ = run_scenarios(config, daily, profiles,
                                 horizon_days=args.horizon, selection=selection)

    payload = build_payload(plan, config, daily, risks=risks, scenarios=scenarios)
    written = write_payload(payload, args.output)
    size_kb = written.stat().st_size / 1024
    _log(f"payload written to {written} ({size_kb:,.0f} KB)")
    return 0


def cmd_all(args) -> int:
    for step in (cmd_generate, cmd_backtest, cmd_plan, cmd_rta, cmd_web):
        print(f"\n=== {step.__name__.replace('cmd_', '').upper()} ===")
        code = step(args)
        if code:
            return code
    return 0


def _interval_index(clock: str) -> int:
    hours, minutes = (int(x) for x in clock.split(":"))
    return int(np.clip((hours * 60 + minutes) // 30, 0, INTERVALS_PER_DAY))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dcww_planning",
        description="Retail contact centre resource planning and forecast engine (synthetic data).",
    )
    parser.add_argument("--data", default=str(DATA), help="dataset directory (default: data)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("generate", help="write the synthetic dataset").set_defaults(func=cmd_generate)
    sub.add_parser("backtest", help="rolling-origin accuracy and model selection").set_defaults(func=cmd_backtest)

    plan_parser = sub.add_parser("plan", help="build the plan and export the Excel pack")
    plan_parser.add_argument("--horizon", type=int, default=182, help="horizon in days (default: 182)")
    plan_parser.add_argument("--refresh", action="store_true", help="re-run the backtest")
    plan_parser.add_argument("--no-scenarios", action="store_true", help="skip scenario runs")
    plan_parser.set_defaults(func=cmd_plan)

    rta_parser = sub.add_parser("rta", help="in-day analysis for one day")
    rta_parser.add_argument("--date", help="YYYY-MM-DD (default: latest trading day)")
    rta_parser.add_argument("--elapsed-time", default="13:00", help="position time (default: 13:00)")
    rta_parser.set_defaults(func=cmd_rta)

    web_parser = sub.add_parser("web", help="JSON payload for the browser demo")
    web_parser.add_argument("--horizon", type=int, default=182)
    web_parser.add_argument("--refresh", action="store_true")
    web_parser.add_argument("--output", default="../planning-engine-data.json")
    web_parser.set_defaults(func=cmd_web)

    all_parser = sub.add_parser("all", help="run everything in order")
    all_parser.add_argument("--horizon", type=int, default=182)
    all_parser.add_argument("--refresh", action="store_true")
    all_parser.add_argument("--no-scenarios", action="store_true")
    all_parser.add_argument("--date", default=None)
    all_parser.add_argument("--elapsed-time", default="13:00")
    all_parser.add_argument("--output", default="../planning-engine-data.json")
    all_parser.set_defaults(func=cmd_all)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
