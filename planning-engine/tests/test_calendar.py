"""Bank holidays are checked against the real published dates.

These are not self-consistency checks. Every date below is the actual
England & Wales bank holiday as published by GOV.UK, including the
substitute days, because a calendar that is internally consistent and
wrong still breaks every March and every Christmas.
"""

from datetime import date

import pytest

from dcww_planning.calendarwales import (
    EVENT_NAMES, bank_holidays, easter_sunday, event_flags, is_bank_holiday, retail_events,
)


@pytest.mark.parametrize("year,expected", [
    (2024, date(2024, 3, 31)),
    (2025, date(2025, 4, 20)),
    (2026, date(2026, 4, 5)),
    (2027, date(2027, 3, 28)),
    (2028, date(2028, 4, 16)),
])
def test_easter_sunday_matches_published_dates(year, expected):
    assert easter_sunday(year) == expected


def test_2026_holidays_match_published_list():
    days = bank_holidays(2026)
    assert date(2026, 1, 1) in days
    assert date(2026, 4, 3) in days      # Good Friday
    assert date(2026, 4, 6) in days      # Easter Monday
    assert date(2026, 5, 4) in days      # Early May
    assert date(2026, 5, 25) in days     # Spring
    assert date(2026, 8, 31) in days     # Summer
    assert date(2026, 12, 25) in days
    # Boxing Day 2026 is a Saturday, so it substitutes to Monday 28th.
    assert date(2026, 12, 28) in days
    assert "substitute" in days[date(2026, 12, 28)]
    assert date(2026, 12, 26) not in days


def test_christmas_on_saturday_pushes_boxing_day_to_tuesday():
    """2027: Christmas Saturday, Boxing Day Sunday.

    The substitutes must not collide - Christmas takes the Monday, so
    Boxing Day has to roll on to the Tuesday. A naive "next weekday"
    rule applied independently puts both on the Monday and loses a
    holiday.
    """
    days = bank_holidays(2027)
    assert date(2027, 12, 27) in days
    assert date(2027, 12, 28) in days
    assert days[date(2027, 12, 27)].startswith("Christmas Day")
    assert days[date(2027, 12, 28)].startswith("Boxing Day")


def test_every_year_has_eight_holidays():
    for year in range(2024, 2031):
        assert len(bank_holidays(year)) == 8, year


def test_no_holiday_falls_on_a_weekend():
    for year in range(2024, 2031):
        for day in bank_holidays(year):
            assert day.weekday() < 5, (year, day)


def test_is_bank_holiday():
    assert is_bank_holiday(date(2026, 4, 6))
    assert not is_bank_holiday(date(2026, 4, 7))


def test_event_flags_are_bounded_and_complete():
    days = [date(2026, 1, 1) + __import__("datetime").timedelta(days=i) for i in range(365)]
    flags = event_flags(days)
    assert set(flags) == set(EVENT_NAMES)
    for name, column in flags.items():
        assert len(column) == len(days)
        assert min(column) >= 0.0, name
        assert max(column) <= 1.0, name


def test_charges_notification_precedes_the_april_tariff_change():
    """Customers must be told before the price changes.

    Encoded as a test because the whole billing demand profile hangs off
    this ordering: the February contact wave is a response to the
    notification, not to the tariff itself.
    """
    events = {e.name: e.day for e in retail_events(2026)}
    assert events["annual_charges_notification"] < events["april_tariff_change"]


def test_events_land_inside_their_year():
    for event in retail_events(2026):
        for day in event.window():
            assert day.year in (2026, 2027)
