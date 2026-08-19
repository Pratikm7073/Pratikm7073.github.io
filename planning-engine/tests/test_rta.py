"""Real Time Analysis: in-day re-forecast, adherence, exceptions."""

import numpy as np
import pytest

from dcww_planning.config import INTERVALS_PER_DAY
from dcww_planning.rta import (
    project_service_level, recommend_actions, reforecast_intraday, schedule_adherence,
)
from datetime import date


def _profile() -> np.ndarray:
    """A plain 08:00-18:00 profile, flat across the open window."""
    profile = np.zeros(INTERVALS_PER_DAY)
    profile[16:36] = 1.0
    return profile / profile.sum()


def test_damping_rises_through_the_day():
    """A morning wobble is noise; the same wobble at four o'clock is signal.

    An undamped re-forecast chases every early variance, and an RTA desk
    that acts on all of them spends its overtime budget before lunch.
    """
    profile = _profile()
    actuals = np.zeros(INTERVALS_PER_DAY)
    actuals[16:36] = 55.0                     # running 10% hot against 50/interval
    dampings = [
        reforecast_intraday(date(2026, 9, 7), "l", profile, 1000.0, actuals, e).damping_applied
        for e in (18, 22, 26, 30, 34)
    ]
    assert all(a < b for a, b in zip(dampings, dampings[1:]))
    assert dampings[0] < 0.5 < dampings[-1]


def test_early_variance_is_only_partly_carried_through():
    profile = _profile()
    actuals = np.zeros(INTERVALS_PER_DAY)
    actuals[16:36] = 60.0                     # 20% above a 50/interval forecast
    position = reforecast_intraday(date(2026, 9, 7), "l", profile, 1000.0, actuals, 18)
    assert position.variance_pct == pytest.approx(20.0, abs=0.5)
    # The revision is real but damped well below the raw variance.
    assert 0 < position.revision_pct < 20.0


def test_full_day_elapsed_reproduces_the_actual():
    """With nothing left to forecast, the revision is just the outturn."""
    profile = _profile()
    actuals = np.zeros(INTERVALS_PER_DAY)
    actuals[16:36] = 57.0
    position = reforecast_intraday(date(2026, 9, 7), "l", profile, 1000.0, actuals,
                                   INTERVALS_PER_DAY)
    assert position.revised_day_forecast == pytest.approx(actuals.sum())
    assert position.revised_remaining.sum() == 0.0


def test_no_elapsed_time_leaves_the_forecast_alone():
    profile = _profile()
    position = reforecast_intraday(date(2026, 9, 7), "l", profile, 1000.0,
                                   np.zeros(INTERVALS_PER_DAY), 0)
    assert position.revised_day_forecast == pytest.approx(1000.0)
    assert position.revision_pct == pytest.approx(0.0)


def test_on_forecast_day_needs_no_revision():
    profile = _profile()
    actuals = profile * 1000.0
    position = reforecast_intraday(date(2026, 9, 7), "l", profile, 1000.0, actuals, 26)
    assert position.variance_pct == pytest.approx(0.0, abs=1e-6)
    assert position.revised_day_forecast == pytest.approx(1000.0, rel=1e-6)


# ── Adherence ──────────────────────────────────────────────────────────

def test_adherence_and_conformance_differ_when_cover_is_mistimed():
    """The failure mode that conformance cannot see.

    Everybody worked their hours, just not when the queue needed them.
    Conformance says 100%; adherence says otherwise, and adherence is the
    one that predicts service level.
    """
    scheduled = np.zeros(INTERVALS_PER_DAY)
    actual = np.zeros(INTERVALS_PER_DAY)
    scheduled[16:36] = 10.0
    actual[16:26] = 15.0        # five too many all morning
    actual[26:36] = 5.0         # five too few all afternoon

    result = schedule_adherence(scheduled, actual)
    assert result.conformance_pct == pytest.approx(100.0)
    assert result.adherence_pct == pytest.approx(75.0)
    assert result.understaffed_hours == pytest.approx(25.0)
    assert result.overstaffed_hours == pytest.approx(25.0)


def test_perfect_adherence():
    scheduled = np.zeros(INTERVALS_PER_DAY)
    scheduled[16:36] = 12.0
    result = schedule_adherence(scheduled, scheduled.copy())
    assert result.adherence_pct == pytest.approx(100.0)
    assert result.understaffed_hours == 0.0


def test_worst_intervals_are_ranked_by_shortfall():
    scheduled = np.zeros(INTERVALS_PER_DAY)
    actual = np.zeros(INTERVALS_PER_DAY)
    scheduled[16:36] = 10.0
    actual[16:36] = 10.0
    actual[20] = 2.0            # biggest gap
    actual[24] = 6.0
    result = schedule_adherence(scheduled, actual)
    assert result.worst_intervals[0][0] == "10:00"
    assert result.worst_intervals[0][1] == pytest.approx(8.0)
    assert result.worst_intervals[1][1] == pytest.approx(4.0)


def test_empty_schedule_is_not_a_division_by_zero():
    result = schedule_adherence(np.zeros(INTERVALS_PER_DAY), np.zeros(INTERVALS_PER_DAY))
    assert result.adherence_pct == 100.0


# ── Projection and actions ─────────────────────────────────────────────

def test_service_level_projection_improves_with_staffing(config):
    channel = config.channel("voice")
    contacts = np.zeros(INTERVALS_PER_DAY)
    contacts[16:36] = 120.0
    thin = project_service_level(contacts, np.full(INTERVALS_PER_DAY, 28.0), channel, 402.0)
    thick = project_service_level(contacts, np.full(INTERVALS_PER_DAY, 40.0), channel, 402.0)
    assert (thick[16:36] >= thin[16:36]).all()
    assert thick[16:36].min() > thin[16:36].min()


def test_actions_only_raised_for_intervals_that_miss_target(config):
    channel = config.channel("voice")
    contacts = np.zeros(INTERVALS_PER_DAY)
    contacts[16:36] = 120.0
    generous = recommend_actions(contacts, np.full(INTERVALS_PER_DAY, 60.0), channel, 402.0)
    assert generous == []

    thin = recommend_actions(contacts, np.full(INTERVALS_PER_DAY, 25.0), channel, 402.0)
    assert thin
    for action in thin:
        assert action["projected_sl"] < channel.service_level_target
        assert action["deficit_fte"] > 0
        assert action["recommended_action"]


def test_escalation_ladder_matches_the_size_of_the_gap(config):
    """Small gaps get free levers; large ones get overtime."""
    channel = config.channel("voice")
    contacts = np.zeros(INTERVALS_PER_DAY)
    contacts[20] = 400.0
    actions = recommend_actions(contacts, np.zeros(INTERVALS_PER_DAY), channel, 402.0)
    assert actions
    assert "Overtime" in actions[0]["recommended_action"]
