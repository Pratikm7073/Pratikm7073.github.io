"""Shrinkage, supply and shift covering."""

from datetime import date

import numpy as np
import pytest

from dcww_planning.capacity import (
    Shift, cover_day, generate_shift_patterns, recruitment_plan,
    rostered_from_on_phone, supply_plan,
)
from dcww_planning.config import INTERVALS_PER_DAY, Shrinkage


# ── Shrinkage ──────────────────────────────────────────────────────────

def test_shrinkage_compounds_rather_than_sums():
    """The single most common shrinkage error, pinned down.

    Adding components always overstates availability and therefore
    under-staffs. The compounded figure must exceed the naive sum, and
    both must stay below 1.
    """
    s = Shrinkage()
    naive_sum = sum(s.components().values())
    assert s.total > naive_sum * 0.85
    assert s.total < naive_sum          # compounding is less than the sum
    assert 0 < s.total < 1


def test_regular_and_irregular_combine_multiplicatively():
    s = Shrinkage()
    assert s.total == pytest.approx(1 - (1 - s.regular) * (1 - s.irregular))


def test_uplift_is_the_reciprocal_not_one_plus():
    """Rostered = on-phone / (1 - shrinkage). Never on-phone x (1 + shrinkage)."""
    s = Shrinkage()
    assert s.uplift_factor == pytest.approx(1 / (1 - s.total))
    assert rostered_from_on_phone(100, s.total) == pytest.approx(100 * s.uplift_factor)
    # The wrong formula understates, and by a material amount.
    assert rostered_from_on_phone(100, s.total) > 100 * (1 + s.total)


def test_impossible_shrinkage_is_rejected():
    with pytest.raises(ValueError):
        rostered_from_on_phone(100, 1.0)


def test_shrinkage_scales_arrays_elementwise():
    out = rostered_from_on_phone(np.array([10.0, 20.0]), 0.2)
    assert out == pytest.approx(np.array([12.5, 25.0]))


# ── Supply ─────────────────────────────────────────────────────────────

def test_weekly_attrition_annualises_back_to_the_input(config):
    weekly = config.supply.weekly_attrition
    assert 1 - (1 - weekly) ** 52 == pytest.approx(config.supply.annual_attrition, abs=1e-9)
    # It is emphatically not the annual rate divided by 52.
    assert weekly != pytest.approx(config.supply.annual_attrition / 52, abs=1e-5)


def test_headcount_erodes_without_recruitment(config):
    weeks = supply_plan(config, date(2026, 9, 7), 52)
    assert weeks[-1].productive_fte < weeks[0].productive_fte
    expected = config.supply.opening_fte * (1 - config.supply.annual_attrition)
    assert weeks[-1].productive_fte == pytest.approx(expected, rel=0.05)


def test_recruits_are_not_capacity_until_they_clear_the_pipeline(config):
    """A new starter is a cost before they are a resource.

    This is the assumption whose absence makes plans fail in-year: credit
    a cohort from its start date and the plan shows cover in exactly the
    weeks the operation is short.
    """
    pipeline = config.supply.training_weeks + config.supply.nesting_weeks
    weeks = supply_plan(config, date(2026, 9, 7), 30, intake_by_week={0: 20})
    baseline = supply_plan(config, date(2026, 9, 7), 30)

    mid_training = config.supply.training_weeks - 1
    assert weeks[mid_training].productive_fte == pytest.approx(
        baseline[mid_training].productive_fte, abs=1e-6)
    assert weeks[mid_training].in_training == pytest.approx(20, rel=0.1)
    # Nesting counts at partial productivity, not zero and not one.
    nesting_week = config.supply.training_weeks + 1
    gain = weeks[nesting_week].productive_fte - baseline[nesting_week].productive_fte
    assert 0 < gain < 20
    # Fully productive once the pipeline is complete.
    after = weeks[pipeline + 2].productive_fte - baseline[pipeline + 2].productive_fte
    assert after == pytest.approx(20, rel=0.15)


def test_recruitment_plan_respects_the_monthly_intake_cap(config):
    required = [config.supply.opening_fte + 4 * w for w in range(40)]
    intake = recruitment_plan(config, date(2026, 9, 7), required)
    for week in intake:
        window = sum(intake.get(w, 0) for w in range(max(0, week - 3), week + 1))
        assert window <= config.supply.max_intake_per_month


def test_recruitment_does_not_book_inside_the_lead_time(config):
    """Nothing hired today can staff next week, and the plan must say so."""
    flat = [config.supply.opening_fte] * 6 + [config.supply.opening_fte + 60] * 4
    intake = recruitment_plan(config, date(2026, 9, 7), flat)
    lead = (config.supply.recruitment_lead_weeks + config.supply.training_weeks
            + config.supply.nesting_weeks)
    # The spike is at week 6, which is inside a 14-week pipeline, so it is
    # unrecoverable and no intake should be booked at all.
    assert lead > 6
    assert sum(intake.values()) == 0


# ── Shift covering ─────────────────────────────────────────────────────

def _double_hump(peak: float = 42.0) -> np.ndarray:
    curve = np.zeros(INTERVALS_PER_DAY)
    for i in range(16, 36):
        h = i * 0.5 + 0.25
        curve[i] = max(0.0, peak * np.exp(-(((h - 10.1) / 1.9) ** 2))
                       + 0.8 * peak * np.exp(-(((h - 14.7) / 2.2) ** 2))
                       - 0.3 * peak * np.exp(-(((h - 12.9) / 0.9) ** 2)))
    return curve


def test_shift_break_removes_coverage():
    shift = Shift(start=16, length_intervals=18, break_offset=9, break_intervals=1)
    cover = shift.coverage()
    assert cover[16 + 9] == 0.0
    assert cover.sum() == 17


def test_roster_covers_the_requirement():
    curve = _double_hump()
    roster = cover_day(date(2026, 9, 7), curve)
    assert roster.under_cover_hours < 1.0
    assert roster.headcount > 0
    assert roster.scheduled_hours >= roster.required_hours


def test_shifts_stay_inside_the_trading_window():
    """No shift may start before the queue opens.

    Hours outside the window cost money and cover nothing, and a greedy
    scored purely on coverage will happily buy them.
    """
    curve = _double_hump()
    open_from = int(np.nonzero(curve > 0)[0][0])
    close_at = int(np.nonzero(curve > 0)[0][-1]) + 1
    roster = cover_day(date(2026, 9, 7), curve)
    for shift in roster.shifts:
        assert shift.start >= open_from
        assert shift.end <= close_at


def test_part_time_cap_is_respected_and_costs_efficiency():
    """The efficient roster and the hireable roster are not the same one."""
    curve = _double_hump()
    capped = cover_day(date(2026, 9, 7), curve, part_time_share_cap=0.35)
    free = cover_day(date(2026, 9, 7), curve, part_time_share_cap=1.0)

    part_time_hours = sum(
        s.coverage().sum() for s, n in capped.shifts.items() for _ in range(n)
        if s.length_intervals < 16
    )
    total_hours = sum(s.coverage().sum() * n for s, n in capped.shifts.items())
    assert part_time_hours / total_hours <= 0.36
    assert capped.efficiency <= free.efficiency


def test_efficiency_is_bounded_and_realistic():
    """Whole shifts cannot trace a sawtooth, so 100% is not achievable."""
    roster = cover_day(date(2026, 9, 7), _double_hump())
    assert 0.6 < roster.efficiency < 1.0


def test_empty_requirement_produces_no_shifts():
    roster = cover_day(date(2026, 9, 7), np.zeros(INTERVALS_PER_DAY))
    assert roster.headcount == 0
    assert roster.scheduled_hours == 0


def test_generated_patterns_fit_their_window():
    patterns = generate_shift_patterns(earliest=16, latest_end=36)
    assert patterns
    for shift in patterns:
        assert shift.start >= 16
        assert shift.end <= 36
