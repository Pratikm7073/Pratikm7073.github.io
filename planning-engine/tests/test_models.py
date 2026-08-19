"""Feature construction, structural-break detection and the models.

These tests exploit the one advantage synthetic data gives: the answers
are known. The generator plants a structural break on two specific lines
and a four-day incident on the operational ones, so detection can be
tested against ground truth rather than against plausibility.
"""

from datetime import date, timedelta

import numpy as np
import pytest

from dcww_planning.features import build_design, detect_level_shift, flag_outliers, open_mask
from dcww_planning.models import MODEL_REGISTRY, RidgeLog, SeasonalNaive
from dcww_planning.regression import ridge_gcv
from dcww_planning.synth import MAJOR_INCIDENT, STRUCTURAL_BREAK

CUT = date(2026, 5, 16)


def _series(daily, config, key):
    subset = daily[daily["line_key"] == key].sort_values("date")
    return list(subset["date"]), subset["offered"].to_numpy(float), config.line(key)


def _split(days, y):
    history = [d for d in days if d <= CUT]
    return history, y[:len(history)], [d for d in days if d > CUT], y[len(history):]


def wape(actual, forecast):
    actual = np.asarray(actual, float)
    forecast = np.asarray(forecast, float)
    return float(np.abs(actual - forecast).sum() / np.abs(actual).sum() * 100)


# ── Regression solver ──────────────────────────────────────────────────

def test_ridge_recovers_a_known_linear_system():
    """With a negligible penalty, ridge must reproduce ordinary least squares."""
    rng = np.random.default_rng(0)
    n = 400
    X = np.column_stack([np.ones(n), rng.normal(size=n), rng.normal(size=n) * 3 + 2])
    true = np.array([5.0, -2.0, 0.75])
    y = X @ true + rng.normal(0, 0.05, n)
    beta, _ = ridge_gcv(X, y, (1e-8,))
    assert beta == pytest.approx(true, abs=0.02)


def test_ridge_shrinks_towards_zero_as_the_penalty_grows():
    rng = np.random.default_rng(1)
    n = 200
    X = np.column_stack([np.ones(n), rng.normal(size=n)])
    y = X @ np.array([3.0, 2.0]) + rng.normal(0, 0.5, n)
    light, _ = ridge_gcv(X, y, (1e-6,))
    heavy, _ = ridge_gcv(X, y, (1e6,))
    assert abs(heavy[1]) < abs(light[1])
    # The intercept is never penalised, so the level survives.
    assert heavy[0] == pytest.approx(float(y.mean()), rel=0.05)


# ── Opening mask ───────────────────────────────────────────────────────

def test_open_mask_excludes_closed_days(config):
    days = [date(2026, 4, 1) + timedelta(days=i) for i in range(14)]
    weekday_line = config.line("billing.voice")
    mask = open_mask(weekday_line, days)
    for day, is_open in zip(days, mask):
        if day.weekday() == 6:
            assert not is_open, day        # closed Sundays
    # Good Friday and Easter Monday 2026 are closed for a weekday queue.
    assert not mask[days.index(date(2026, 4, 3))]
    assert not mask[days.index(date(2026, 4, 6))]


def test_always_on_line_trades_through_bank_holidays(config):
    days = [date(2026, 4, 1) + timedelta(days=i) for i in range(14)]
    mask = open_mask(config.line("operations.voice"), days)
    assert mask.all()


# ── Design matrix ──────────────────────────────────────────────────────

def test_design_matrix_is_finite_and_named(config):
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(400)]
    line = config.line("billing.voice")
    design = build_design(days, line, None)
    assert design.X.shape[0] == len(days)
    assert design.X.shape[1] == len(design.names)
    assert np.isfinite(design.X).all()
    assert "const" in design.names
    assert "trend_years" in design.names
    assert any(n.startswith("annual_sin") for n in design.names)
    # Only the events this line is actually sensitive to are carried.
    assert "event_annual_charges_notification" in design.names
    assert "event_freeze_thaw" not in design.names


def test_level_shift_column_only_appears_when_requested(config):
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(400)]
    line = config.line("billing.voice")
    assert "level_shift" not in build_design(days, line, None).names
    with_shift = build_design(days, line, date(2025, 6, 2))
    assert "level_shift" in with_shift.names
    column = with_shift.X[:, with_shift.names.index("level_shift")]
    assert column.min() == 0.0
    assert column.max() == pytest.approx(1.0)
    # Zero before the shift, ramping afterwards.
    assert column[days.index(date(2025, 5, 1))] == 0.0
    assert column[days.index(date(2025, 12, 1))] == pytest.approx(1.0)


# ── Structural break detection ─────────────────────────────────────────

@pytest.mark.parametrize("key", ["billing.voice", "billing.webchat"])
def test_detects_the_planted_structural_break(daily, config, key):
    """The generator plants a deflection on exactly these two lines."""
    days, y, line = _series(daily, config, key)
    result = RidgeLog().fit_predict(line, *_split(days, y)[:2], _split(days, y)[2])
    detected = result.diagnostics["level_shift"]
    assert detected is not None, f"{key}: planted break was missed"
    found = date.fromisoformat(detected)
    assert abs((found - STRUCTURAL_BREAK["date"]).days) <= 21


@pytest.mark.parametrize("key", ["operations.voice", "welsh.voice", "movehome.voice", "quality.voice"])
def test_no_false_positive_break_on_unaffected_lines(daily, config, key):
    """A detector that fires everywhere is worse than none at all.

    These lines have trends and strong seasonality but no planted break.
    Reporting one would send a planner looking for a change that never
    happened.
    """
    days, y, line = _series(daily, config, key)
    history, history_y, future, _ = _split(days, y)
    result = RidgeLog().fit_predict(line, history, history_y, future)
    assert result.diagnostics["level_shift"] is None, f"{key}: false positive"


def test_break_detection_needs_evidence_not_just_noise(config):
    """Pure noise around a flat level must not produce a break."""
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(700)]
    rng = np.random.default_rng(7)
    line = config.line("movehome.voice")
    log_y = np.log1p(500 + rng.normal(0, 40, len(days)))
    assert detect_level_shift(days, log_y, line) is None


# ── Outliers ───────────────────────────────────────────────────────────

def test_outlier_rule_flags_extremes_not_ordinary_variation():
    rng = np.random.default_rng(3)
    residuals = rng.normal(0, 0.1, 800)
    assert flag_outliers(residuals).sum() <= 8       # ~0 expected at z=3.5
    residuals[400] = 2.5
    residuals[401] = -2.2
    flags = flag_outliers(residuals)
    assert flags[400] and flags[401]


def test_incident_days_are_excluded_from_the_fit(daily, config):
    """The planted trunk-main incident must be found and set aside.

    It is real demand, but it is not what a normal Tuesday looks like, and
    leaving it in the fit drags the level up for every future week.
    """
    days, y, line = _series(daily, config, "operations.voice")
    history, history_y, future, _ = _split(days, y)
    result = RidgeLog().fit_predict(line, history, history_y, future)
    flagged = {date.fromisoformat(d) for d in result.diagnostics["outlier_dates"]}
    incident = {MAJOR_INCIDENT["start"] + timedelta(days=i) for i in range(MAJOR_INCIDENT["days"])}
    assert flagged & incident, "the incident was not detected as anomalous"


# ── Forecast quality ───────────────────────────────────────────────────

@pytest.mark.parametrize("key", ["billing.voice", "operations.voice", "affordability.voice"])
def test_models_beat_the_naive_baseline(daily, config, key):
    """The baseline exists to be beaten, and beating it is not automatic."""
    days, y, line = _series(daily, config, key)
    history, history_y, future, future_y = _split(days, y)
    naive = wape(future_y, SeasonalNaive().fit_predict(line, history, history_y, future).mean)
    for model in ("decomposition", "ridge_log"):
        error = wape(future_y, MODEL_REGISTRY[model]().fit_predict(
            line, history, history_y, future).mean)
        assert error < naive, f"{key}: {model} ({error:.1f}%) did not beat naive ({naive:.1f}%)"


def test_forecasts_are_non_negative_and_zero_when_closed(daily, config):
    days, y, line = _series(daily, config, "billing.voice")
    history, history_y, future, _ = _split(days, y)
    for name in MODEL_REGISTRY:
        result = MODEL_REGISTRY[name]().fit_predict(line, history, history_y, future)
        assert (result.mean >= 0).all(), name
        for day, value in zip(result.days, result.mean):
            if day.weekday() == 6:
                assert value == 0.0, f"{name} forecast volume on a closed Sunday"


def test_prediction_interval_brackets_the_forecast(daily, config):
    days, y, line = _series(daily, config, "billing.voice")
    history, history_y, future, _ = _split(days, y)
    result = RidgeLog().fit_predict(line, history, history_y, future)
    trading = result.mean > 0
    assert (result.p10[trading] <= result.mean[trading]).all()
    assert (result.p90[trading] >= result.mean[trading]).all()


def test_short_history_falls_back_rather_than_failing(config):
    """Not enough data is a normal condition, not an exception."""
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(40)]
    y = np.full(len(days), 300.0)
    future = [days[-1] + timedelta(days=i + 1) for i in range(14)]
    result = RidgeLog().fit_predict(config.line("billing.voice"), days, y, future)
    assert len(result.mean) == len(future)
    assert np.isfinite(result.mean).all()
