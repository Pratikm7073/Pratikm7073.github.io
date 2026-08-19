"""Accuracy metrics and rolling-origin evaluation."""

from datetime import date, timedelta

import numpy as np
import pytest

from dcww_planning.backtest import HORIZON_BUCKETS, rolling_origin, score, tracking_signal


def test_metrics_against_a_hand_computed_example():
    actual = np.array([100.0, 200.0, 300.0])
    forecast = np.array([110.0, 180.0, 330.0])
    result = score(actual, forecast, "line", "model", "in_week")

    # Absolute errors 10, 20, 30 = 60 over a total of 600.
    assert result.wape == pytest.approx(10.0)
    # Percentage errors 10%, 10%, 10% -> MAPE 10%.
    assert result.mape == pytest.approx(10.0)
    # Signed errors +10, -20, +30 = +20 over 600.
    assert result.bias_pct == pytest.approx(20 / 600 * 100)
    assert result.n_obs == 3


def test_wape_and_mape_disagree_on_low_volume_days():
    """Why WAPE is the headline and MAPE is the footnote.

    A twelve-contact miss on a sixty-contact queue is a 20% MAPE
    contribution weighted equally with a four-thousand-call day. WAPE
    weights by volume, which is what a resource plan actually cares
    about.
    """
    actual = np.array([60.0, 4000.0])
    forecast = np.array([48.0, 4000.0])
    result = score(actual, forecast, "line", "model", "in_week")
    assert result.mape == pytest.approx(10.0)         # (20% + 0%) / 2
    assert result.wape < 0.4                          # 12 out of 4060


def test_closed_days_are_excluded_from_scoring():
    """Predicting zero on a closed Sunday is not accuracy.

    Leaving those days in would make a weekday-only queue look more
    accurate than a 24/7 one purely because it is shut more often.
    """
    with_closed = score(np.array([0.0, 0.0, 100.0]), np.array([0.0, 0.0, 90.0]),
                        "l", "m", "in_week")
    without = score(np.array([100.0]), np.array([90.0]), "l", "m", "in_week")
    assert with_closed.wape == pytest.approx(without.wape)
    assert with_closed.n_obs == 1


def test_perfect_forecast_scores_zero():
    actual = np.array([10.0, 20.0, 30.0])
    result = score(actual, actual.copy(), "l", "m", "in_week")
    assert result.wape == 0.0
    assert result.bias_pct == 0.0
    assert result.bias_ratio == 0.0


def test_bias_is_signed_and_wape_is_not():
    """A model can be accurate and consistently wrong in one direction."""
    actual = np.array([100.0] * 10)
    high = score(actual, actual * 1.05, "l", "m", "in_week")
    low = score(actual, actual * 0.95, "l", "m", "in_week")
    assert high.wape == pytest.approx(low.wape)
    assert high.bias_pct > 0 > low.bias_pct
    assert high.bias_ratio == pytest.approx(1.0)


def test_tracking_signal_uses_a_trailing_window():
    """Accumulated without bound it always eventually breaches.

    A forecast in calibration wanders around zero; one that has drifted
    marches away from it. Only the trailing window distinguishes them.
    """
    drifting = np.full(60, 5.0)
    assert tracking_signal(drifting, window=12) == pytest.approx(12.0)
    balanced = np.array([5.0, -5.0] * 30)
    assert abs(tracking_signal(balanced, window=12)) < 1e-9


def test_empty_input_does_not_raise():
    result = score(np.array([]), np.array([]), "l", "m", "in_week")
    assert result.n_obs == 0
    assert np.isnan(result.wape)


def test_rolling_origin_scores_every_horizon_out_of_sample(daily, config):
    subset = daily[daily["line_key"] == "billing.voice"].sort_values("date")
    results = rolling_origin(
        config.line("billing.voice"),
        list(subset["date"]), subset["offered"].to_numpy(float),
        models=("seasonal_naive", "ridge_log"),
        step_days=56,
    )
    horizons = {a.horizon for a in results}
    assert horizons == {label for label, _, _ in HORIZON_BUCKETS}
    for accuracy in results:
        assert accuracy.n_obs > 0
        assert 0 <= accuracy.wape < 100

    ridge = {a.horizon: a.wape for a in results if a.model == "ridge_log"}
    naive = {a.horizon: a.wape for a in results if a.model == "seasonal_naive"}
    for horizon in ridge:
        assert ridge[horizon] < naive[horizon], horizon


def test_rolling_origin_returns_nothing_without_enough_history(config):
    days = [date(2026, 1, 1) + timedelta(days=i) for i in range(100)]
    y = np.full(100, 500.0)
    assert rolling_origin(config.line("billing.voice"), days, y) == []
