"""Demand forecasting models for daily contact volume.

Three models, deliberately spanning the range from "what the operation
does today" to "what the operation could do", plus a combination:

1. `SeasonalNaive` - last four same-weekdays, median. This is the honest
   baseline. Any model that cannot beat it does not deserve to be in the
   plan, and quoting accuracy without a baseline is how forecasting
   projects get oversold.

2. `MultiplicativeDecomposition` - the classic planner's method: strip out
   weekly shape, fit the trend, take an annual index, apply named event
   uplifts. It is what a good Excel model does, and it is included because
   it is transparent, it is what the incumbent process looks like, and it
   is a genuinely strong performer on stable series.

3. `RidgeLog` - regularised regression on log volume with the full
   calendar and event design matrix, fitted in two passes so that outlier
   exclusion and structural-break detection operate on residuals rather
   than raw volume.

4. `Ensemble` - inverse-error weighted combination of the above.

Selection between them is not a matter of taste: `backtest.py` runs a
rolling-origin evaluation per service line and the winner is whichever
model actually forecast best at the horizon that matters.

**On the log transform.** All models predict in log space and
retransform. The naive `exp(fitted)` is biased low, because the
exponential of a mean is not the mean of an exponential. Duan's smearing
estimator corrects it by multiplying by `mean(exp(residuals))`. On a
series with 20% residual spread this is worth about 2% of volume, which
across a year of staffing is real money.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date

import numpy as np

from .config import ServiceLine
from .features import build_design, detect_level_shift, flag_outliers, open_mask
from .regression import ridge_gcv

__all__ = [
    "ForecastResult", "Forecaster", "SeasonalNaive",
    "MultiplicativeDecomposition", "RidgeLog", "Ensemble", "MODEL_REGISTRY",
]


@dataclass
class ForecastResult:
    """A forecast plus everything needed to defend it."""

    days: list[date]
    mean: np.ndarray
    p10: np.ndarray
    p90: np.ndarray
    model: str
    line_key: str
    diagnostics: dict = field(default_factory=dict)

    def as_rows(self) -> list[dict]:
        return [
            {
                "date": d,
                "line_key": self.line_key,
                "model": self.model,
                "forecast": float(m),
                "p10": float(lo),
                "p90": float(hi),
            }
            for d, m, lo, hi in zip(self.days, self.mean, self.p10, self.p90)
        ]


class Forecaster(ABC):
    """Common interface: fit on history, predict named future days.

    Fit and predict are one call rather than two because the design matrix
    has to be built across history and future together - the trend origin
    and the column set must be identical on both sides, and building them
    separately is a reliable way to produce a silent column misalignment
    that shows up as a mysterious level error weeks later.
    """

    name = "base"

    @abstractmethod
    def fit_predict(
        self, line: ServiceLine, history_days: list[date], y: np.ndarray, future_days: list[date]
    ) -> ForecastResult:
        ...


# ─────────────────────────────────────────────────────────────────────
# Baseline
# ─────────────────────────────────────────────────────────────────────

class SeasonalNaive(Forecaster):
    """Median of the last `lookback` same-weekdays.

    Median rather than mean so a single incident week does not poison the
    baseline - which would flatter every other model in the comparison and
    make the whole evaluation dishonest.
    """

    name = "seasonal_naive"

    def __init__(self, lookback: int = 4):
        self.lookback = lookback

    def fit_predict(self, line, history_days, y, future_days):
        y = np.asarray(y, dtype=float)
        open_hist = open_mask(line, history_days)
        by_weekday: dict[int, list[float]] = {}
        for d, value, is_open in zip(history_days, y, open_hist):
            if is_open:
                by_weekday.setdefault(d.weekday(), []).append(float(value))

        levels = {
            w: float(np.median(v[-self.lookback:])) for w, v in by_weekday.items() if v
        }
        spread = {
            w: float(np.std(v[-max(self.lookback, 8):]) or 0.0) for w, v in by_weekday.items() if v
        }

        open_future = open_mask(line, future_days)
        mean = np.array([
            levels.get(d.weekday(), 0.0) if is_open else 0.0
            for d, is_open in zip(future_days, open_future)
        ])
        sd = np.array([
            spread.get(d.weekday(), 0.0) if is_open else 0.0
            for d, is_open in zip(future_days, open_future)
        ])
        return ForecastResult(
            days=list(future_days), mean=mean,
            p10=np.maximum(mean - 1.2816 * sd, 0.0), p90=mean + 1.2816 * sd,
            model=self.name, line_key=line.key,
            diagnostics={"weekday_levels": levels},
        )


# ─────────────────────────────────────────────────────────────────────
# Classic decomposition
# ─────────────────────────────────────────────────────────────────────

class MultiplicativeDecomposition(Forecaster):
    """Trend x day-of-week index x annual index x event uplift.

    The method a competent planner already runs in Excel, implemented
    honestly so the comparison is fair. Each stage divides its effect out
    before the next is estimated, which is what keeps the indices from
    absorbing one another.
    """

    name = "decomposition"

    def __init__(self, trend_window: int = 91):
        self.trend_window = trend_window

    def fit_predict(self, line, history_days, y, future_days):
        y = np.asarray(y, dtype=float)
        mask = open_mask(line, history_days)
        days = [d for d, keep in zip(history_days, mask) if keep]
        values = y[mask]
        if len(values) < 120:
            return SeasonalNaive().fit_predict(line, history_days, y, future_days)

        # The order of these steps is not cosmetic. Each stage divides its
        # own effect out before the next is estimated, and getting the
        # sequence wrong produces a model that is confidently, badly
        # wrong rather than obviously broken:
        #
        #   events before trend  - otherwise a winter of burst-main spikes
        #                          reads as an upward trend and gets
        #                          extrapolated straight through summer;
        #   outliers after events - an incident is only an outlier once
        #                          the known events are accounted for,
        #                          and flagging beforehand deletes the
        #                          event days the uplifts are estimated
        #                          from;
        #   trend last           - fitted to a series with weekly shape,
        #                          events and annual seasonality already
        #                          removed, so the slope means what it
        #                          says.

        # 1. Day-of-week index, from the ratio to a centred weekly mean.
        centred = _centred_mean(values, 7)
        ratio = np.where(centred > 0, values / np.maximum(centred, 1e-9), np.nan)
        dow_index: dict[int, float] = {}
        for w in sorted({d.weekday() for d in days}):
            sel = np.array([d.weekday() == w for d in days])
            vals = ratio[sel & ~np.isnan(ratio)]
            dow_index[w] = float(np.median(vals)) if len(vals) else 1.0
        norm = float(np.mean(list(dow_index.values()))) or 1.0
        dow_index = {w: v / norm for w, v in dow_index.items()}
        deseasonalised = values / np.array([dow_index[d.weekday()] for d in days])

        # 2. Event uplifts, measured against a long centred mean so the
        #    comparison is to the local level rather than the series mean.
        long_level = _centred_mean(deseasonalised, self.trend_window)
        event_ratio = np.where(long_level > 0, deseasonalised / np.maximum(long_level, 1e-9), np.nan)
        event_uplift = _event_uplifts(line, days, event_ratio)

        history_events = _event_matrix(line, days)
        event_factor = np.array([
            float(np.prod([1.0 + event_uplift.get(n, 0.0) * i for n, i in ev.items()])) if ev else 1.0
            for ev in history_events
        ])
        de_evented = deseasonalised / np.maximum(event_factor, 1e-6)

        # 3. Outliers: what is left once weekday shape and known events
        #    are removed. The November trunk-main incident lands here,
        #    because "trunk main burst" is not in the event vocabulary.
        clean = ~_local_outliers(de_evented)

        # 4. Annual index by ISO week, measured against a fitted long-run
        #    trend line rather than a moving average.
        #
        #    This is the subtle one. The textbook recipe takes the ratio
        #    to a centred moving average, and for an *annual* index that
        #    average has to be 365 days wide - anything narrower follows
        #    the annual cycle itself, so the ratio comes out at roughly
        #    1.0 everywhere and the seasonal index collapses to flat. The
        #    symptom is a forecast that never comes down in summer on a
        #    winter-peaking queue, which on the 24/7 operational lines is
        #    a 40-point WAPE error rather than a subtlety.
        #
        #    Two and a half years of history cannot support a 365-day
        #    centred window at the edges, so the long-run level is fitted
        #    explicitly as a robust line instead. With a short history a
        #    linear trend plus an annual index is identifiable; a 365-day
        #    moving average is not.
        position = np.arange(len(de_evented), dtype=float)
        if clean.sum() > 30:
            long_slope, long_intercept = np.polyfit(position[clean], de_evented[clean], 1)
        else:
            long_slope, long_intercept = np.polyfit(position, de_evented, 1)
        trend_line = np.maximum(long_intercept + long_slope * position, 1e-9)
        annual_ratio = np.where(clean, de_evented / trend_line, np.nan)
        week_index: dict[int, float] = {}
        for w in range(1, 54):
            sel = np.array([d.isocalendar()[1] == w for d in days])
            vals = annual_ratio[sel & ~np.isnan(annual_ratio)]
            if len(vals):
                week_index[w] = float(np.median(vals))
        week_index = _smooth_cyclic(week_index)

        level = de_evented / np.array([week_index.get(d.isocalendar()[1], 1.0) for d in days])

        # 5. Trend on the last year of fully adjusted, outlier-free level.
        tail = min(len(level), 365)
        tail_level = level[-tail:]
        tail_clean = clean[-tail:]
        t = np.arange(tail, dtype=float)
        if tail_clean.sum() > 30:
            slope, intercept = np.polyfit(t[tail_clean], tail_level[tail_clean], 1)
        else:
            slope, intercept = np.polyfit(t, tail_level, 1)
        level_end = intercept + slope * (tail - 1)

        # Guard rail: a daily slope fitted to one noisy year can imply an
        # absurd annual movement. Cap it at +/-35% a year of the current
        # level. This is a judgement call and it is stated as one - it
        # trades a little accuracy on a genuinely fast-moving series for
        # protection against the slope running away on a quiet one.
        if level_end > 0:
            cap = 0.35 * level_end / 365.0
            slope = float(np.clip(slope, -cap, cap))

        # 6. Project.
        open_future = open_mask(line, future_days)
        future_events = _event_matrix(line, future_days)
        mean = np.zeros(len(future_days))
        for i, (d, is_open) in enumerate(zip(future_days, open_future)):
            if not is_open:
                continue
            base = level_end + slope * _damped_steps(i + 1)
            value = base * dow_index.get(d.weekday(), 1.0) * week_index.get(d.isocalendar()[1], 1.0)
            for name, intensity in future_events[i].items():
                value *= 1.0 + event_uplift.get(name, 0.0) * intensity
            mean[i] = max(value, 0.0)

        spread = float(np.std(level[clean] / np.maximum(level_end, 1e-9))) if clean.sum() > 10 else 0.15
        sd = spread * mean
        return ForecastResult(
            days=list(future_days), mean=mean,
            p10=np.maximum(mean - 1.2816 * sd, 0.0), p90=mean + 1.2816 * sd,
            model=self.name, line_key=line.key,
            diagnostics={
                "dow_index": {int(k): round(v, 4) for k, v in dow_index.items()},
                "event_uplift": {k: round(v, 4) for k, v in event_uplift.items()},
                "trend_slope_per_day": float(slope),
                "level_end": float(level_end),
                "outliers_excluded": int((~clean).sum()),
            },
        )


def _local_outliers(values: np.ndarray, window: int = 29, z: float = 4.0) -> np.ndarray:
    """MAD outlier rule against a local median.

    Used on a level series rather than on residuals, so it needs a local
    window: the series still carries annual seasonality, and a global
    median would flag every January on a weather-driven queue.
    """
    n = len(values)
    flags = np.zeros(n, dtype=bool)
    half = window // 2
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        local = np.concatenate([values[lo:i], values[i + 1:hi]])
        if len(local) < 8:
            continue
        med = np.median(local)
        mad = np.median(np.abs(local - med))
        if mad <= 0:
            continue
        if abs(values[i] - med) / (1.4826 * mad) > z:
            flags[i] = True
    return flags


def _damped_steps(horizon: int, phi: float = 0.985) -> float:
    """Cumulative damped trend increment `phi + phi^2 + ... + phi^h`.

    An undamped linear trend fitted to a year of daily data and pushed out
    twenty-four months produces headcount numbers nobody will sign off:
    it says the direction of travel continues at exactly today's slope
    forever. Damping expresses the honest position - the direction is
    informative, the slope is not, that far out - and converges the
    projection to a finite ceiling of `slope * phi / (1 - phi)` rather
    than letting it run away.
    """
    if horizon <= 0:
        return 0.0
    return float(phi * (1.0 - phi ** horizon) / (1.0 - phi))


def _centred_mean(values: np.ndarray, window: int, nan_safe: bool = False) -> np.ndarray:
    """Centred rolling mean with shrinking windows at the edges.

    `nan_safe` lets the caller blank out excluded observations with NaN
    and have them skipped, rather than having to interpolate over them
    first.
    """
    n = len(values)
    half = window // 2
    out = np.zeros(n)
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        chunk = values[lo:hi]
        if nan_safe:
            chunk = chunk[~np.isnan(chunk)]
            out[i] = chunk.mean() if len(chunk) else np.nan
        else:
            out[i] = chunk.mean()
    return out


def _smooth_cyclic(index: dict[int, float], passes: int = 2) -> dict[int, float]:
    """Smooth a week-of-year index around the year boundary.

    Week 52 and week 1 are neighbours. Smoothing them as if they sat at
    opposite ends of a line puts a discontinuity right in the middle of
    the festive period, which is the last place a contact centre wants
    one.
    """
    weeks = sorted(index)
    if not weeks:
        return {}
    out = dict(index)
    for _ in range(passes):
        prev = dict(out)
        for i, w in enumerate(weeks):
            before = prev[weeks[(i - 1) % len(weeks)]]
            after = prev[weeks[(i + 1) % len(weeks)]]
            out[w] = 0.25 * before + 0.5 * prev[w] + 0.25 * after
    scale = float(np.mean(list(out.values()))) or 1.0
    return {w: v / scale for w, v in out.items()}


def _event_matrix(line: ServiceLine, days: list[date]) -> list[dict[str, float]]:
    from .calendarwales import event_flags
    flags = event_flags(days)
    return [
        {name: flags[name][i] for name in line.event_sensitivity if flags[name][i] > 0}
        for i in range(len(days))
    ]


def _event_uplifts(line: ServiceLine, days: list[date], residual_ratio: np.ndarray) -> dict[str, float]:
    """Estimate each event's proportional uplift from unexplained ratio."""
    from .calendarwales import event_flags
    flags = event_flags(days)
    uplifts: dict[str, float] = {}
    for name in line.event_sensitivity:
        intensity = np.asarray(flags[name], dtype=float)
        strong = intensity > 0.6
        if strong.sum() < 5:
            continue
        quiet = intensity == 0
        if quiet.sum() < 20:
            continue
        baseline = float(np.median(residual_ratio[quiet]))
        during = float(np.median(residual_ratio[strong]))
        if baseline > 0:
            uplifts[name] = max(during / baseline - 1.0, -0.9)
    return uplifts


# ─────────────────────────────────────────────────────────────────────
# Regularised regression
# ─────────────────────────────────────────────────────────────────────

class RidgeLog(Forecaster):
    """Ridge regression on log volume over the calendar/event design.

    Fitted in two passes:

    1. Fit on all open days. Take residuals.
    2. From those residuals, flag outliers and detect a structural break.
       Refit excluding the outliers and including a level-shift regressor
       if one was found.

    Ridge rather than ordinary least squares because the event regressors
    are correlated with each other and with the annual harmonics - the
    charges notification always lands in February - and unregularised
    coefficients on collinear columns swing wildly between refits. A
    planner who sees the February uplift move from +18% to +31% because
    one more week of data arrived stops believing the model.
    """

    name = "ridge_log"

    def __init__(self, lambdas: tuple[float, ...] = (0.05, 0.2, 1.0, 5.0, 20.0, 100.0)):
        self.lambdas = lambdas

    def fit_predict(self, line, history_days, y, future_days):
        y = np.asarray(y, dtype=float)
        mask = open_mask(line, history_days)
        fit_days = [d for d, keep in zip(history_days, mask) if keep]
        fit_y = y[mask]
        if len(fit_y) < 90:
            return SeasonalNaive().fit_predict(line, history_days, y, future_days)

        all_days = list(history_days) + list(future_days)
        target = np.log1p(fit_y)

        # ── Pass 1: is there a structural break? ──
        # Tested by refitting at candidate dates and scoring on BIC, not
        # by scanning residuals - see `detect_level_shift` for why the
        # obvious approach gives confidently wrong answers here.
        shift = detect_level_shift(fit_days, target, line, self.lambdas)

        design = build_design(all_days, line, shift)
        rows = {d: i for i, d in enumerate(all_days)}
        idx = np.array([rows[d] for d in fit_days])
        X_all = design.X[idx]
        beta, lam = ridge_gcv(X_all, target, self.lambdas)

        # ── Pass 2: flag what the fitted model cannot explain, refit ──
        outliers = flag_outliers(target - X_all @ beta)
        keep = ~outliers
        if keep.sum() > X_all.shape[1] + 30:
            beta, lam = ridge_gcv(X_all[keep], target[keep], self.lambdas)
        else:
            keep = np.ones(len(target), dtype=bool)

        residuals = target[keep] - X_all[keep] @ beta

        # Coefficients come from the trimmed fit, but the retransformation
        # factor is computed over *all* residuals including the excluded
        # days. Incidents are overwhelmingly upward spikes, so trimming
        # them and then also trimming the smearing estimate biases the
        # central forecast low twice over. Robust shape, unbiased level.
        full_residuals = target - X_all @ beta
        sigma = float(np.std(residuals, ddof=1)) if len(residuals) > 2 else 0.0
        # Duan's smearing estimator: corrects the retransformation bias
        # from forecasting in log space and exponentiating back.
        smearing = float(np.mean(np.exp(full_residuals))) if len(full_residuals) else 1.0

        open_future = open_mask(line, future_days)
        future_idx = np.array([rows[d] for d in future_days])
        log_mean = design.X[future_idx] @ beta
        mean = (np.expm1(log_mean) + 1.0) * smearing - 1.0
        mean = np.where(open_future, np.maximum(mean, 0.0), 0.0)

        p10 = np.where(open_future, np.maximum(np.expm1(log_mean - 1.2816 * sigma) * smearing, 0.0), 0.0)
        p90 = np.where(open_future, np.maximum(np.expm1(log_mean + 1.2816 * sigma) * smearing, 0.0), 0.0)

        return ForecastResult(
            days=list(future_days), mean=mean, p10=p10, p90=p90,
            model=self.name, line_key=line.key,
            diagnostics={
                "lambda": lam,
                "sigma_log": round(sigma, 4),
                "smearing": round(smearing, 4),
                "level_shift": str(shift) if shift else None,
                "outliers_excluded": int(outliers.sum()),
                "outlier_dates": [str(d) for d, f in zip(fit_days, outliers) if f],
                "coefficients": {n: round(float(b), 4) for n, b in zip(design.names, beta)},
            },
        )


# ─────────────────────────────────────────────────────────────────────
# Ensemble
# ─────────────────────────────────────────────────────────────────────

class Ensemble(Forecaster):
    """Inverse-error weighted blend of the member models.

    Weights come from the rolling-origin backtest, not from the fit.
    Weighting by in-sample fit rewards whichever model over-fits hardest,
    which is precisely backwards.
    """

    name = "ensemble"

    def __init__(self, members: dict[str, float] | None = None):
        self.members = members or {"ridge_log": 0.5, "decomposition": 0.35, "seasonal_naive": 0.15}

    def fit_predict(self, line, history_days, y, future_days):
        total = sum(self.members.values()) or 1.0
        stacked = np.zeros(len(future_days))
        p10 = np.zeros(len(future_days))
        p90 = np.zeros(len(future_days))
        for name, weight in self.members.items():
            result = MODEL_REGISTRY[name]().fit_predict(line, history_days, y, future_days)
            w = weight / total
            stacked += w * result.mean
            p10 += w * result.p10
            p90 += w * result.p90
        return ForecastResult(
            days=list(future_days), mean=stacked, p10=p10, p90=p90,
            model=self.name, line_key=line.key,
            diagnostics={"weights": {k: round(v / total, 4) for k, v in self.members.items()}},
        )


MODEL_REGISTRY: dict[str, type[Forecaster]] = {
    "seasonal_naive": SeasonalNaive,
    "decomposition": MultiplicativeDecomposition,
    "ridge_log": RidgeLog,
    "ensemble": Ensemble,
}
