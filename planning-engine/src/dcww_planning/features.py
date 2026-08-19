"""Design matrix construction for the daily demand models.

Every column produced here is nameable in English. That is a hard
requirement rather than a stylistic preference: a forecast a planner
cannot explain to an Operations Manager is a forecast that gets overridden
in the review meeting, and an overridden forecast is worse than no model
at all. When this engine says February is up 18%, the matrix can say
which named regressor carried it.

The matrix covers four families:

* **Trend** - one linear term on a per-year scale, plus an optional level
  shift for a detected structural break.
* **Weekly seasonality** - day-of-week dummies rather than Fourier terms,
  because a planner reads "Monday +18%" and does not read a sine phase.
* **Annual seasonality** - Fourier terms, because the annual shape is
  smooth and 52 weekly dummies would over-fit two years of history.
* **Calendar and business events** - bank holiday adjacency plus the
  dated Retail event set.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from .calendarwales import EVENT_NAMES, bank_holidays, event_flags
from .config import ServiceLine
from .regression import ridge_gcv

__all__ = [
    "DesignMatrix", "build_design", "open_mask", "detect_level_shift",
    "flag_outliers", "ramp_column", "DEFAULT_LAMBDAS", "RAMP_DAYS",
]

ANNUAL_HARMONICS = 3
RAMP_DAYS = 56
DEFAULT_LAMBDAS = (0.05, 0.2, 1.0, 5.0, 20.0, 100.0)


@dataclass
class DesignMatrix:
    X: np.ndarray            # (n, k)
    names: list[str]
    days: list[date]

    def __len__(self) -> int:
        return self.X.shape[0]

    def subset(self, mask: np.ndarray) -> "DesignMatrix":
        return DesignMatrix(
            X=self.X[mask],
            names=self.names,
            days=[d for d, keep in zip(self.days, mask) if keep],
        )


# ─────────────────────────────────────────────────────────────────────
# Opening mask
# ─────────────────────────────────────────────────────────────────────

def open_mask(line: ServiceLine, days: list[date]) -> np.ndarray:
    """True on days this line actually trades.

    Closed days are excluded from the fit rather than modelled as zeros.
    Fitting through a structural zero drags the whole level down and
    corrupts every other coefficient - a Saturday-closed back-office queue
    would otherwise learn a "Saturday effect" of minus one hundred per
    cent and smear it into the weekday estimates.
    """
    holidays: dict[date, str] = {}
    for year in sorted({d.year for d in days}):
        holidays.update(bank_holidays(year))

    always_on = all(w == (0.0, 24.0) for w in line.hours.by_weekday if w is not None) and all(
        w is not None for w in line.hours.by_weekday
    )

    mask = np.zeros(len(days), dtype=bool)
    for i, d in enumerate(days):
        if line.hours.by_weekday[d.weekday()] is None:
            continue
        if d in holidays and not always_on:
            continue
        mask[i] = True
    return mask


# ─────────────────────────────────────────────────────────────────────
# Design matrix
# ─────────────────────────────────────────────────────────────────────

def build_design(
    days: list[date],
    line: ServiceLine,
    level_shift_date: date | None = None,
) -> DesignMatrix:
    """Assemble the regressor matrix for one service line."""
    n = len(days)
    origin = days[0]
    cols: list[np.ndarray] = []
    names: list[str] = []

    def add(name: str, values: np.ndarray) -> None:
        cols.append(np.asarray(values, dtype=float))
        names.append(name)

    add("const", np.ones(n))
    add("trend_years", np.array([(d - origin).days / 365.25 for d in days]))

    # Weekly seasonality. Monday is the reference level, so every other
    # coefficient reads directly as "versus a Monday".
    weekdays = np.array([d.weekday() for d in days])
    present = sorted({int(w) for w in weekdays})
    labels = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    for w in present[1:]:
        add(f"dow_{labels[w]}", (weekdays == w).astype(float))

    # Annual seasonality via Fourier terms.
    doy = np.array([d.timetuple().tm_yday for d in days], dtype=float)
    for k in range(1, ANNUAL_HARMONICS + 1):
        angle = 2 * np.pi * k * doy / 365.25
        add(f"annual_sin_{k}", np.sin(angle))
        add(f"annual_cos_{k}", np.cos(angle))

    # Bank holiday adjacency. The holiday itself is usually excluded by
    # the opening mask; what survives is the displaced demand around it.
    holidays: dict[date, str] = {}
    for year in sorted({d.year for d in days}):
        holidays.update(bank_holidays(year))

    add("day_after_bh", np.array([1.0 if (d - timedelta(days=1)) in holidays else 0.0 for d in days]))
    add("two_days_after_bh", np.array([1.0 if (d - timedelta(days=2)) in holidays else 0.0 for d in days]))
    add("day_before_bh", np.array([1.0 if (d + timedelta(days=1)) in holidays else 0.0 for d in days]))
    add("festive_period", np.array([
        1.0 if (d.month == 12 and d.day >= 20) or (d.month == 1 and d.day <= 3) else 0.0
        for d in days
    ]))

    # Business events - only those this line is actually sensitive to.
    # Carrying all eleven for every line would spend degrees of freedom on
    # regressors that cannot matter (a storm does not move the move-home
    # queue) and would make the coefficients harder to defend.
    flags = event_flags(days)
    for name in EVENT_NAMES:
        if name not in line.event_sensitivity:
            continue
        intensity = np.asarray(flags[name], dtype=float)
        add(f"event_{name}", intensity)

        # A graded event needs a quadratic term as well as a linear one.
        # The underlying response is multiplicative in volume - an event
        # at half intensity multiplies demand by (1 + s/2) - so in log
        # space it is log(1 + s*I), which is *concave* in I. A single
        # linear term in log space cannot represent that curvature: fit it
        # to the peak days and it over-predicts the shoulders, fit it to
        # the shoulders and it under-predicts the peak. Either way the
        # residuals on event days blow up and the outlier detector then
        # throws away the very days the event regressor exists to explain.
        #
        # Events with only one intensity level (no decay tail) are skipped:
        # squaring a 0/1 column reproduces it exactly and the two columns
        # would be perfectly collinear.
        if len(np.unique(intensity[intensity > 0])) > 2:
            add(f"event_{name}_sq", intensity ** 2)

    # Structural break: a step from the shift date onward, ramped over
    # eight weeks to match how adoption-driven deflection actually lands.
    if level_shift_date is not None:
        add("level_shift", ramp_column(days, level_shift_date))

    return DesignMatrix(X=np.column_stack(cols), names=names, days=list(days))


# ─────────────────────────────────────────────────────────────────────
# Residual diagnostics
# ─────────────────────────────────────────────────────────────────────
#
# Both detectors below operate on **model residuals**, never on raw
# volume. That distinction is the whole point and it is worth stating
# plainly, because doing it the obvious way gives confidently wrong
# answers:
#
# * Scanning raw volume for a level shift finds one in every series,
#   because annual seasonality guarantees that some split separates a
#   busy half from a quiet half. The "structural break" it reports is
#   just February.
# * Flagging raw volume as anomalous flags every freeze-thaw week on the
#   operational line. Those spikes are not anomalies - they are the event
#   regressors doing their job, and removing them would delete the very
#   signal the model needs.
#
# Run both on the residuals of a fitted model and each asks the right
# question: what is left that the calendar, the seasonality and the known
# events cannot account for?


def ramp_column(days: list[date], shift_date: date, ramp_days: int = RAMP_DAYS) -> np.ndarray:
    """A level-shift regressor that ramps in rather than stepping.

    Real deflection does not land overnight - customers discover a new
    self-serve journey over weeks. Modelling it as an instantaneous step
    forces the estimator to split the difference across the adoption
    period and understates the eventual size of the shift.
    """
    return np.array([
        min(1.0, max(0.0, (d - shift_date).days / ramp_days)) for d in days
    ])


def detect_level_shift(
    days: list[date],
    log_y: np.ndarray,
    line: ServiceLine,
    lambdas: tuple[float, ...] = DEFAULT_LAMBDAS,
    stride: int = 7,
    min_segment: int = 90,
    min_step: float = 0.04,
    min_bic_gain: float = 10.0,
) -> date | None:
    """Test for a permanent level shift by refitting at each candidate date.

    The obvious approach - fit the model, scan its residuals for a step -
    does not work here, and it is worth being explicit about why, because
    it fails silently and confidently.

    A level shift that ramps in over eight weeks, viewed through two years
    of history, is very nearly collinear with a free linear trend. The
    trend term simply absorbs it: the residuals come out flat, the scan
    finds nothing, and the model quietly attributes a one-off portal
    launch to organic decline - which then gets extrapolated forward
    forever. On the sibling series the same collinearity produces the
    opposite failure, where an over-fitted trend leaves a spurious step in
    the residuals and the scan reports a break that never happened.

    The fix is to make the trend and the shift compete directly. For each
    candidate date, refit the *whole* model with a ramp regressor added,
    and score it with BIC. The shift is accepted only when it is both
    decisively better on BIC and materially large - so a break is reported
    when the data genuinely cannot be explained by trend alone, and not
    otherwise.

    Candidates are scanned every `stride` days rather than daily. Daily
    resolution on a change that takes eight weeks to land is false
    precision, and it costs eight times the compute inside the backtest
    loop.
    """
    log_y = np.asarray(log_y, dtype=float)
    n = len(log_y)
    if n < 2 * min_segment + 30:
        return None

    base = build_design(days, line, None)
    beta, lam = ridge_gcv(base.X, log_y, lambdas)
    rss0 = float(((log_y - base.X @ beta) ** 2).sum())
    if rss0 <= 0:
        return None
    k0 = base.X.shape[1]
    bic0 = n * np.log(rss0 / n) + k0 * np.log(n)

    best_bic, best_date, best_coef = np.inf, None, 0.0
    for i in range(min_segment, n - min_segment, stride):
        candidate = days[i]
        # Append the ramp to the already-built design rather than
        # rebuilding it: the other twenty-odd columns do not depend on the
        # candidate date, and rebuilding them per candidate is the
        # difference between a backtest that runs in seconds and one that
        # runs in minutes.
        X = np.column_stack([base.X, ramp_column(days, candidate)])
        b, _ = ridge_gcv(X, log_y, (lam,))
        rss = float(((log_y - X @ b) ** 2).sum())
        if rss <= 0:
            continue
        bic = n * np.log(rss / n) + (k0 + 1) * np.log(n)
        if bic < best_bic:
            best_bic, best_date, best_coef = bic, candidate, float(b[-1])

    if best_date is None:
        return None
    if (bic0 - best_bic) < min_bic_gain or abs(best_coef) < min_step:
        return None
    return best_date


def flag_outliers(residuals: np.ndarray, z: float = 3.5) -> np.ndarray:
    """Flag observations the fitted model cannot account for.

    Uses a median/MAD rule, which is robust to the very outliers it is
    looking for - a mean-and-standard-deviation rule gets dragged towards
    a four-day incident and then fails to flag it. The 1.4826 factor
    scales MAD to a standard-deviation equivalent under normality, so `z`
    keeps its usual interpretation.

    Flagged days are excluded from refitting but are **not** deleted from
    history. An incident that generated seven times normal volume is real
    demand that really had to be answered; it belongs in the risk case and
    the resilience conversation, just not in the estimate of what a normal
    Tuesday looks like.
    """
    residuals = np.asarray(residuals, dtype=float)
    med = np.median(residuals)
    mad = np.median(np.abs(residuals - med))
    if mad <= 0:
        return np.zeros(len(residuals), dtype=bool)
    return np.abs(residuals - med) / (1.4826 * mad) > z
