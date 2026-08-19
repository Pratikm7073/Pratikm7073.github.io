"""Synthetic history generator for the Retail contact operation.

Why synthetic, and why say so loudly: real contact centre data is
commercially sensitive and cannot be published. What *can* be published is
a generator whose output has the same structure as the real thing, plus a
documented schema so real extracts drop straight in. Everything the
forecasting side of this engine does works identically on either.

A deliberate design constraint: **this module shares no seasonal code with
`features.py` or `models.py`.** The generator writes its own trend, weekly
shape, annual curve and intraday profile from scratch. If the estimator
imported the generator's shapes, the backtest would be measuring its own
reflection. Keeping them apart means the reported accuracy is earned.

The generated series carries the things that actually make contact centre
forecasting hard, not just a clean sine wave:

* a **structural break** - a self-serve/chatbot launch that permanently
  deflects voice into web chat, which a naive model will average through
  for months;
* a **major incident** - a multi-day operational spike that must be
  detected and excluded from the fit rather than learned as seasonality;
* **overdispersion** - day-to-day variance well above Poisson, because
  arrivals cluster;
* **AHT drift** - handle time rising with new-starter intake and with
  query complexity during billing events.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd

from .calendarwales import bank_holidays, event_flags
from .config import INTERVAL_MINUTES, INTERVALS_PER_DAY, PlanConfig, ServiceLine, default_config

__all__ = ["generate_history", "GenerationResult", "STRUCTURAL_BREAK", "MAJOR_INCIDENT"]


# Known planted anomalies. They are module constants rather than hidden
# magic so the tests - and the README - can state exactly what the
# detectors are expected to find.
STRUCTURAL_BREAK = {
    "date": date(2025, 6, 2),
    "label": "Self-serve billing portal + chatbot launch",
    "voice_deflection": 0.115,     # billing voice permanently down 11.5%
    "webchat_uplift": 0.28,        # billing web chat permanently up 28%
}

MAJOR_INCIDENT = {
    "start": date(2025, 11, 24),
    "days": 4,
    "label": "Trunk main burst - multi-zone supply interruption",
    "operational_multiplier": 7.5,
    "billing_multiplier": 1.25,
}


class GenerationResult:
    """Container for the generated frames."""

    def __init__(self, daily: pd.DataFrame, interval: pd.DataFrame, profiles: pd.DataFrame):
        self.daily = daily
        self.interval = interval
        self.profiles = profiles


# ─────────────────────────────────────────────────────────────────────
# Shape helpers (generator-side only)
# ─────────────────────────────────────────────────────────────────────

def _annual_curve(days: list[date], peak_week: int, amplitude: float) -> np.ndarray:
    """Annual seasonality as a cosine peaking in `peak_week`."""
    doy = np.array([d.timetuple().tm_yday for d in days], dtype=float)
    phase = 2 * np.pi * (doy - peak_week * 7) / 365.25
    return 1.0 + amplitude * np.cos(phase)


def _trend(days: list[date], per_year: float) -> np.ndarray:
    """Compound growth from the first day of history."""
    origin = days[0]
    years = np.array([(d - origin).days / 365.25 for d in days], dtype=float)
    return (1.0 + per_year) ** years


def _holiday_factor(days: list[date], line: ServiceLine) -> np.ndarray:
    """Bank holiday closure and the rebound that follows it.

    Demand is displaced, not destroyed. A queue that closes on the Monday
    sees roughly a quarter more volume on the Tuesday, and planners who
    forecast the closure but not the rebound miss the day that actually
    breaks service level.
    """
    holidays = {}
    for year in sorted({d.year for d in days}):
        holidays.update(bank_holidays(year))

    factor = np.ones(len(days))
    always_on = all(w is not None and w == (0.0, 24.0) for w in line.hours.by_weekday)

    for i, d in enumerate(days):
        if d in holidays:
            factor[i] = 0.55 if always_on else 0.0
        elif (d - timedelta(days=1)) in holidays:
            factor[i] = 1.10 if always_on else 1.26
        elif (d - timedelta(days=2)) in holidays and d.weekday() < 5:
            factor[i] = 1.06

        # Christmas/New Year lull: even the 24/7 lines run quiet.
        if (d.month == 12 and d.day >= 24) or (d.month == 1 and d.day <= 2):
            factor[i] *= 0.72 if always_on else 0.45

    return factor


def _event_factor(days: list[date], line: ServiceLine) -> np.ndarray:
    """Uplift from dated business events, per this line's sensitivity."""
    flags = event_flags(days)
    factor = np.ones(len(days))
    for name, sensitivity in line.event_sensitivity.items():
        factor += sensitivity * np.asarray(flags[name], dtype=float)
    return factor


def _break_factor(days: list[date], line: ServiceLine) -> np.ndarray:
    """The self-serve launch: a permanent level shift with a ramp.

    Real deflection does not land overnight - adoption ramps over about
    eight weeks. That ramp is exactly what makes a level shift hard to
    tell apart from a trend change in the first two months.
    """
    factor = np.ones(len(days))
    if line.queue != "Billing & payments":
        return factor

    if line.channel == "voice":
        target = -STRUCTURAL_BREAK["voice_deflection"]
    elif line.channel == "webchat":
        target = STRUCTURAL_BREAK["webchat_uplift"]
    else:
        return factor

    launch = STRUCTURAL_BREAK["date"]
    for i, d in enumerate(days):
        elapsed = (d - launch).days
        if elapsed < 0:
            continue
        adoption = min(1.0, elapsed / 56.0)
        factor[i] = 1.0 + target * adoption
    return factor


def _incident_factor(days: list[date], line: ServiceLine) -> np.ndarray:
    """A multi-day operational incident with a decaying tail."""
    factor = np.ones(len(days))
    if line.queue == "Leaks & supply interruption" or line.queue == "Water quality":
        peak = MAJOR_INCIDENT["operational_multiplier"]
    elif line.queue == "Billing & payments":
        peak = MAJOR_INCIDENT["billing_multiplier"]
    else:
        return factor

    start = MAJOR_INCIDENT["start"]
    span = MAJOR_INCIDENT["days"]
    for i, d in enumerate(days):
        elapsed = (d - start).days
        if 0 <= elapsed < span:
            decay = 1.0 - 0.55 * (elapsed / span)
            factor[i] = 1.0 + (peak - 1.0) * decay
    return factor


def _intraday_weights(line: ServiceLine, weekday: int) -> np.ndarray:
    """Arrival profile across the 48 half-hour intervals of one weekday.

    Two humps with a lunch dip is the shape almost every UK contact centre
    actually produces. The 24/7 operational lines keep a night floor and
    gain an early-morning bump, because that is when people get up and
    find no water.
    """
    window = line.hours.by_weekday[weekday]
    weights = np.zeros(INTERVALS_PER_DAY)
    if window is None:
        return weights

    open_h, close_h = window
    always_on = (open_h, close_h) == (0.0, 24.0)
    centres = (np.arange(INTERVALS_PER_DAY) * INTERVAL_MINUTES + INTERVAL_MINUTES / 2) / 60.0

    for i, h in enumerate(centres):
        if not (open_h <= h < close_h):
            continue
        morning = np.exp(-(((h - 10.1) / 1.85) ** 2))
        afternoon = 0.82 * np.exp(-(((h - 14.7) / 2.15) ** 2))
        lunch_dip = 0.30 * np.exp(-(((h - 12.9) / 0.85) ** 2))
        value = morning + afternoon - lunch_dip

        if always_on:
            night_floor = 0.055
            early = 0.34 * np.exp(-(((h - 7.3) / 1.05) ** 2))
            evening = 0.26 * np.exp(-(((h - 18.6) / 2.4) ** 2))
            value = max(value, 0.0) + night_floor + early + evening
        else:
            # Ramp in over the first half hour and taper over the last
            # hour, so the open and close intervals are not full-strength.
            if h < open_h + 0.5:
                value *= 0.55
            if h > close_h - 1.0:
                value *= 0.60

        weights[i] = max(value, 0.0)

    total = weights.sum()
    return weights / total if total > 0 else weights


def _aht_multiplier(days: list[date], line: ServiceLine, rng: np.random.Generator) -> np.ndarray:
    """Day-level AHT drift.

    Handle time is not a constant, and treating it as one is a bigger
    source of plan error than volume in most operations. It rises with
    new-starter intake, with billing complexity during charges events, and
    on Mondays when queues are busiest and advisors rush less.
    """
    n = len(days)
    mult = np.ones(n)

    # Slow upward drift from complexity and tenure mix, ~2.5% a year.
    origin = days[0]
    years = np.array([(d - origin).days / 365.25 for d in days])
    mult *= 1.0 + 0.025 * years

    # Billing events lengthen calls: more explaining, more payment plans.
    flags = event_flags(days)
    for name, weight in (("annual_charges_notification", 0.09),
                         ("april_tariff_change", 0.07),
                         ("annual_bill_issue", 0.05)):
        if name in line.event_sensitivity:
            mult *= 1.0 + weight * np.asarray(flags[name], dtype=float)

    # Weekday effect and a little day-to-day noise.
    dow = np.array([d.weekday() for d in days])
    mult *= np.where(dow == 0, 1.035, np.where(dow >= 5, 0.965, 1.0))
    mult *= rng.normal(1.0, 0.021, n).clip(0.90, 1.12)

    return mult


# ─────────────────────────────────────────────────────────────────────
# Generation
# ─────────────────────────────────────────────────────────────────────

def generate_history(
    start: date = date(2024, 1, 1),
    end: date = date(2026, 8, 16),
    config: PlanConfig | None = None,
    interval_days: int = 28,
) -> GenerationResult:
    """Generate daily history, recent interval detail, and arrival profiles.

    `interval_days` controls how many days of half-hourly detail are
    materialised. Full-history interval data is hundreds of thousands of
    rows and belongs in a warehouse, not a git repository; the daily frame
    plus a stable profile set reconstructs it whenever the planner needs
    it.
    """
    cfg = config or default_config()
    rng = np.random.default_rng(cfg.seed)

    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    n = len(days)

    holidays: dict[date, str] = {}
    for year in sorted({d.year for d in days}):
        holidays.update(bank_holidays(year))

    daily_rows = []
    profile_rows = []

    for line in cfg.service_lines:
        channel = cfg.channel(line.channel)

        weekly = np.array([line.weekly_shape[d.weekday()] for d in days])
        mean = (
            line.base_daily_volume
            * _trend(days, line.trend_per_year)
            * weekly
            * _annual_curve(days, line.annual_peak_week, line.annual_amplitude)
            * _holiday_factor(days, line)
            * _event_factor(days, line)
            * _break_factor(days, line)
            * _incident_factor(days, line)
        )

        # Overdispersed counts: a lognormal day multiplier on top of a
        # Poisson draw. Pure Poisson is far too well behaved to be a fair
        # test of a forecast - real arrival variance is roughly three to
        # four times the mean.
        day_noise = rng.lognormal(mean=0.0, sigma=0.085, size=n)
        offered = rng.poisson(np.clip(mean * day_noise, 0, None)).astype(float)

        aht = channel.aht_seconds * line.aht_multiplier * _aht_multiplier(days, line, rng)

        # Service outcomes. Deferrable channels do not abandon in the
        # queueing sense, so only the interactive ones carry abandons.
        if channel.kind == "interactive":
            pressure = offered / np.maximum(mean, 1e-9)
            base_sl = 0.845 - 0.30 * np.clip(pressure - 1.0, 0, None)
            sl_attained = np.clip(base_sl + rng.normal(0, 0.045, n), 0.30, 0.99)
            abandon_rate = np.clip(0.022 + 0.115 * np.clip(pressure - 1.0, 0, None)
                                   + rng.normal(0, 0.006, n), 0.002, 0.35)
        else:
            sl_attained = np.clip(0.92 - 0.22 * np.clip(offered / np.maximum(mean, 1e-9) - 1.0, 0, None)
                                  + rng.normal(0, 0.03, n), 0.40, 0.999)
            abandon_rate = np.zeros(n)

        abandoned = np.round(offered * abandon_rate)
        handled = offered - abandoned

        for i, d in enumerate(days):
            daily_rows.append({
                "date": d,
                "line_key": line.key,
                "queue": line.queue,
                "channel": line.channel,
                "welsh_language": line.welsh_language,
                "weekday": d.weekday(),
                "is_bank_holiday": d in holidays,
                "offered": float(offered[i]),
                "handled": float(handled[i]),
                "abandoned": float(abandoned[i]),
                "aht_seconds": float(round(aht[i], 1)),
                "service_level_attained": float(round(sl_attained[i], 4)),
                "workload_hours": float(round(handled[i] * aht[i] / 3600.0, 3)),
            })

        for weekday in range(7):
            weights = _intraday_weights(line, weekday)
            for interval, w in enumerate(weights):
                if w <= 0:
                    continue
                profile_rows.append({
                    "line_key": line.key,
                    "weekday": weekday,
                    "interval": interval,
                    "interval_start": _interval_label(interval),
                    "share": float(round(w, 6)),
                })

    daily = pd.DataFrame(daily_rows)
    profiles = pd.DataFrame(profile_rows)
    interval = _explode_intervals(daily, profiles, cfg, days[-interval_days:], rng)

    return GenerationResult(daily=daily, interval=interval, profiles=profiles)


def _interval_label(interval: int) -> str:
    minutes = interval * INTERVAL_MINUTES
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _explode_intervals(
    daily: pd.DataFrame,
    profiles: pd.DataFrame,
    cfg: PlanConfig,
    days: list[date],
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Spread daily volume across half-hour intervals, plus staffing actuals.

    Interval arrivals are not the daily total times a fixed share: the
    profile itself wobbles day to day. The noise here is what makes the
    Real Time Analysis module non-trivial - if intraday were deterministic
    there would be nothing to re-forecast.
    """
    wanted = set(days)
    sub = daily[daily["date"].isin(wanted)]
    # line -> weekday -> array of interval shares
    nested: dict[str, dict[int, np.ndarray]] = {}
    for r in profiles.itertuples():
        nested.setdefault(r.line_key, {}).setdefault(r.weekday, np.zeros(INTERVALS_PER_DAY))
        nested[r.line_key][r.weekday][r.interval] = r.share

    rows = []
    for rec in sub.itertuples():
        shares = nested.get(rec.line_key, {}).get(rec.weekday)
        if shares is None or shares.sum() <= 0:
            continue

        jitter = rng.normal(1.0, 0.11, INTERVALS_PER_DAY).clip(0.55, 1.55)
        wobbled = shares * jitter
        wobbled = wobbled / wobbled.sum()
        offered = rng.poisson(np.clip(rec.offered * wobbled, 0, None)).astype(float)

        channel = cfg.channel(rec.channel)
        for interval in np.nonzero(shares)[0]:
            volume = offered[interval]
            workload_hours = volume * rec.aht_seconds / 3600.0
            required = workload_hours / (0.5 * channel.concurrency)
            # Actual staffing tracks requirement imperfectly - rosters are
            # built to a forecast made weeks earlier, not to what arrived.
            staffed = max(0.0, required * rng.normal(0.965, 0.13))
            rows.append({
                "date": rec.date,
                "interval": int(interval),
                "interval_start": _interval_label(int(interval)),
                "line_key": rec.line_key,
                "queue": rec.queue,
                "channel": rec.channel,
                "offered": float(volume),
                "aht_seconds": float(rec.aht_seconds),
                "staffed_actual": float(round(staffed, 2)),
                "scheduled": float(round(required * rng.normal(1.0, 0.05), 2)),
            })

    return pd.DataFrame(rows)
