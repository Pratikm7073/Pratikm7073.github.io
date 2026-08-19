"""Rolling-origin backtesting and per-line model selection.

A single holdout tells you how one model did on one arbitrary quarter.
That is not evidence, and quoting it as accuracy is how forecasting work
gets oversold and then quietly distrusted. Rolling-origin evaluation
re-fits the model at many successive cut-off dates and scores each
forecast only against data the model could not see, which is the same
discipline as measuring a live forecast against outturn week after week.

**Metrics, and why these ones.**

* **WAPE** (weighted absolute percentage error) is the headline. It is
  the total absolute error divided by total actual volume, so every
  contact counts the same regardless of which day it landed on.
* **MAPE** is reported because it is what most contact centres quote, but
  it is treated as secondary on purpose: MAPE averages *percentage*
  errors, so a quiet Sunday on the Welsh-language line - sixty calls,
  twelve out - contributes a 20% error with the same weight as a
  four-thousand-call Monday. On low-volume queues MAPE is dominated by
  days nobody staffs to.
* **Bias** is the one planners under-use and the one that actually costs
  money. A model can have excellent WAPE and still run 6% high every
  single week; WAPE cannot see that, and the operation pays for the
  over-staffing all year. Bias is signed and it is reported at every
  horizon.
* **Bias ratio** - mean error over mean absolute deviation - is a
  scale-free companion to bias. Beyond roughly +/-0.3 the errors are
  mostly pointing one way rather than scattering, which means there is
  structure left the model has not captured.

The classic **tracking signal** (cumulative error over MAD) is provided
separately, by `tracking_signal()`, for monitoring a live forecast. It is
deliberately not part of the pooled scores: it accumulates with sample
size, so over a thousand pooled backtest observations even a trivial bias
produces a number in the hundreds, which looks like a crisis and is not.
It means something on a running window against outturn, and nothing at
all when pooled.

**Horizon buckets** map to the three planning horizons the role deals in:
in-week (1-7 days, rosters and real-time), short term (8-28 days,
overtime and leave), and medium term (29-91 days, recruitment). The
long-term horizon is deliberately *not* scored: validating a 24-month
forecast needs more than 24 months of history to test on, and reporting
an unvalidated number as accuracy would be exactly the overselling this
module exists to prevent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from .config import PlanConfig, ServiceLine
from .models import MODEL_REGISTRY, Forecaster

__all__ = [
    "HORIZON_BUCKETS", "Accuracy", "score", "rolling_origin",
    "select_models", "SelectionResult", "tracking_signal",
]

# (label, first day, last day) inclusive, in days ahead of the cut-off.
HORIZON_BUCKETS: tuple[tuple[str, int, int], ...] = (
    ("in_week", 1, 7),
    ("short_term", 8, 28),
    ("medium_term", 29, 91),
)


@dataclass
class Accuracy:
    """Error metrics for one model, one line, one horizon bucket."""

    line_key: str
    model: str
    horizon: str
    n_obs: int
    actual_total: float
    wape: float
    mape: float
    bias_pct: float
    bias_ratio: float

    def as_row(self) -> dict:
        return {
            "line_key": self.line_key,
            "model": self.model,
            "horizon": self.horizon,
            "n_obs": self.n_obs,
            "actual_total": round(self.actual_total, 1),
            "wape_pct": round(self.wape, 2),
            "mape_pct": round(self.mape, 2),
            "bias_pct": round(self.bias_pct, 2),
            "bias_ratio": round(self.bias_ratio, 3),
        }


def score(actual: np.ndarray, forecast: np.ndarray, line_key: str, model: str, horizon: str) -> Accuracy:
    """Compute the metric set for one aligned actual/forecast pair.

    Days on which the line was closed are dropped before scoring. They
    are trivially correct - the model predicts zero, zero arrives - and
    leaving them in would deflate WAPE by whatever share of the calendar
    the queue happens to be shut, making a Monday-to-Friday back-office
    queue look more accurate than a 24/7 one for no better reason.
    """
    actual = np.asarray(actual, dtype=float)
    forecast = np.asarray(forecast, dtype=float)
    trading = actual > 0
    actual, forecast = actual[trading], forecast[trading]

    if len(actual) == 0:
        return Accuracy(line_key, model, horizon, 0, 0.0, float("nan"), float("nan"), float("nan"), float("nan"))

    error = forecast - actual
    total = actual.sum()
    abs_error = np.abs(error)

    wape = float(abs_error.sum() / total * 100)
    mape = float(np.mean(abs_error / actual) * 100)
    bias = float(error.sum() / total * 100)
    mad = float(abs_error.mean())
    bias_ratio = float(error.mean() / mad) if mad > 0 else 0.0

    return Accuracy(
        line_key=line_key, model=model, horizon=horizon, n_obs=len(actual),
        actual_total=float(total), wape=wape, mape=mape,
        bias_pct=bias, bias_ratio=bias_ratio,
    )


def tracking_signal(errors: np.ndarray, window: int = 12) -> float:
    """Classic tracking signal over the most recent `window` periods.

    Running sum of forecast errors divided by mean absolute deviation.
    This is the control-chart measure a planner watches week to week: a
    forecast in calibration wanders around zero, and one that has drifted
    marches steadily away from it. The conventional action limit is +/-4,
    at which point the model wants re-fitting rather than trusting.

    Computed on a trailing window, which is the only way it means
    anything - accumulated over an unbounded history it grows with sample
    size and always eventually breaches.
    """
    errors = np.asarray(errors, dtype=float)[-window:]
    if len(errors) == 0:
        return 0.0
    mad = float(np.abs(errors).mean())
    return float(errors.sum() / mad) if mad > 0 else 0.0


def rolling_origin(
    line: ServiceLine,
    days: list[date],
    y: np.ndarray,
    models: tuple[str, ...] = ("seasonal_naive", "decomposition", "ridge_log"),
    min_train_days: int = 420,
    step_days: int = 28,
    max_horizon: int = 91,
) -> list[Accuracy]:
    """Re-fit at successive cut-offs and score each forecast out of sample.

    `min_train_days` is set at roughly fourteen months rather than the
    twelve you might expect. A model carrying annual seasonality needs to
    have seen a full year *plus* enough of the next one to tell a seasonal
    peak apart from a trend; cutting it at exactly 365 days makes the
    first few origins systematically worse and flatters the naive baseline
    in the comparison.
    """
    y = np.asarray(y, dtype=float)
    n = len(days)
    results: list[Accuracy] = []

    origins = list(range(min_train_days, n - max_horizon, step_days))
    if not origins:
        return results

    # Collect errors across all origins first, then score per bucket, so
    # each bucket's metrics pool every origin rather than being averaged
    # over per-origin percentages (which would weight a quiet origin the
    # same as a peak one).
    pooled: dict[tuple[str, str], list[tuple[float, float]]] = {}

    for cut in origins:
        history_days, history_y = days[:cut], y[:cut]
        future_days = days[cut:cut + max_horizon]
        future_y = y[cut:cut + max_horizon]

        for model_name in models:
            forecast = MODEL_REGISTRY[model_name]().fit_predict(
                line, history_days, history_y, future_days
            )
            for label, lo, hi in HORIZON_BUCKETS:
                sel = slice(lo - 1, min(hi, len(future_days)))
                a, f = future_y[sel], forecast.mean[sel]
                pooled.setdefault((model_name, label), []).extend(zip(a, f))

    for (model_name, label), pairs in pooled.items():
        if not pairs:
            continue
        a = np.array([p[0] for p in pairs])
        f = np.array([p[1] for p in pairs])
        results.append(score(a, f, line.key, model_name, label))

    return results


@dataclass
class SelectionResult:
    """The chosen model for one line, and the evidence for choosing it."""

    line_key: str
    chosen: str
    baseline_wape: float
    chosen_wape: float
    improvement_pct: float
    accuracy: list[Accuracy]
    ensemble_weights: dict[str, float]

    @property
    def beats_baseline(self) -> bool:
        return self.chosen_wape < self.baseline_wape


def select_models(
    config: PlanConfig,
    daily: "object",
    models: tuple[str, ...] = ("seasonal_naive", "decomposition", "ridge_log"),
    primary_horizon: str = "short_term",
    **kwargs,
) -> dict[str, SelectionResult]:
    """Backtest every service line and pick a model for each.

    Selection is on the **short-term** bucket by default, because that is
    the horizon the resource plan is most sensitive to: it is where
    overtime is committed, leave is approved and shifts are locked. A
    model that wins at 90 days but drifts at 14 costs more than one that
    is merely adequate far out.

    Ensemble weights are derived here from inverse WAPE, so the blend is
    weighted by out-of-sample performance rather than by taste.
    """
    selections: dict[str, SelectionResult] = {}

    for line in config.service_lines:
        subset = daily[daily["line_key"] == line.key].sort_values("date")
        days = list(subset["date"])
        y = subset["offered"].to_numpy(dtype=float)

        accuracy = rolling_origin(line, days, y, models=models, **kwargs)
        if not accuracy:
            continue

        primary = {a.model: a.wape for a in accuracy if a.horizon == primary_horizon}
        if not primary:
            primary = {a.model: a.wape for a in accuracy}

        chosen = min(primary, key=primary.get)
        baseline = primary.get("seasonal_naive", float("nan"))
        chosen_wape = primary[chosen]

        # Inverse-error weights, restricted to models that at least beat
        # the naive baseline. Including a model that loses to "same
        # weekday last month" drags the blend towards it for no reason.
        eligible = {m: w for m, w in primary.items() if np.isfinite(w) and w > 0 and w <= baseline}
        if not eligible:
            eligible = {chosen: chosen_wape}
        inverse = {m: 1.0 / w for m, w in eligible.items()}
        total = sum(inverse.values())
        weights = {m: v / total for m, v in inverse.items()}

        improvement = (baseline - chosen_wape) / baseline * 100 if baseline else float("nan")
        selections[line.key] = SelectionResult(
            line_key=line.key, chosen=chosen,
            baseline_wape=baseline, chosen_wape=chosen_wape,
            improvement_pct=improvement, accuracy=accuracy,
            ensemble_weights=weights,
        )

    return selections
