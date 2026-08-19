"""Calendar and event model for a Welsh Water Retail contact centre.

Two things drive contact demand in a regulated water retailer, and neither
of them is captured by a plain time index:

1. **The working calendar.** England & Wales bank holidays close the
   contact centre or run it on a skeleton, and they displace demand into
   the surrounding days rather than removing it.
2. **The billing and charges cycle.** A water company's contact demand is
   overwhelmingly billing-led. The annual charges notification, the April
   tariff change and the monthly direct-debit collection dates each throw
   a predictable, dated spike that a pure time-series model will treat as
   noise and smooth away.

Everything here is computed rather than tabulated, so the module stays
correct for any year without a data refresh and without a third-party
holiday dependency that would need pinning and auditing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache

__all__ = [
    "easter_sunday",
    "bank_holidays",
    "is_bank_holiday",
    "CalendarEvent",
    "retail_events",
    "event_flags",
    "EVENT_NAMES",
]


# ─────────────────────────────────────────────────────────────────────
# Bank holidays (England & Wales)
# ─────────────────────────────────────────────────────────────────────

def easter_sunday(year: int) -> date:
    """Gregorian Easter Sunday (anonymous / Meeus-Jones-Butcher algorithm).

    Good Friday and Easter Monday are both bank holidays in England &
    Wales and both move by up to a month between years, so the whole
    spring demand profile shifts with them. Hard-coding them is the
    single most common way a contact centre forecast silently breaks in
    March.
    """
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month, day = divmod(h + l - 7 * m + 114, 31)
    return date(year, month, day + 1)


def _first_weekday(year: int, month: int, weekday: int) -> date:
    """First `weekday` (Mon=0) in the given month."""
    d = date(year, month, 1)
    return d + timedelta(days=(weekday - d.weekday()) % 7)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    """Last `weekday` (Mon=0) in the given month."""
    d = date(year, month, 31) if month != 2 else date(year, month, 28)
    while d.month != month:
        d -= timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


@lru_cache(maxsize=64)
def bank_holidays(year: int) -> dict[date, str]:
    """England & Wales bank holidays for `year`, including substitute days.

    Wales observes the England & Wales set: Wales has no additional
    statutory bank holiday (St David's Day is not one), which is why it is
    carried below as an *observance* rather than a closure.
    """
    easter = easter_sunday(year)
    days: dict[date, str] = {
        easter - timedelta(days=2): "Good Friday",
        easter + timedelta(days=1): "Easter Monday",
        _first_weekday(year, 5, 0): "Early May bank holiday",
        _last_weekday(year, 5, 0): "Spring bank holiday",
        _last_weekday(year, 8, 0): "Summer bank holiday",
    }

    # Fixed-date holidays roll forward to the next free weekday when they
    # land on a weekend. Christmas on a Saturday pushes Boxing Day's
    # substitute to the Tuesday, so the roll has to be sequential.
    taken = set(days)
    for fixed, name in (
        (date(year, 1, 1), "New Year's Day"),
        (date(year, 12, 25), "Christmas Day"),
        (date(year, 12, 26), "Boxing Day"),
    ):
        d = fixed
        substitute = False
        while d.weekday() >= 5 or d in taken:
            d += timedelta(days=1)
            substitute = True
        days[d] = f"{name} (substitute day)" if substitute else name
        taken.add(d)

    return days


def is_bank_holiday(d: date) -> bool:
    return d in bank_holidays(d.year)


# ─────────────────────────────────────────────────────────────────────
# Retail business events
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CalendarEvent:
    """A dated business event with a known demand consequence.

    `lag_days` is how long after the trigger the contact actually arrives.
    A charges notification does not generate calls on the day it is
    printed; it generates them when it lands on doormats and again when
    the customer gets round to phoning. `decay` spreads the effect over
    the following days so the planner sees a realistic tail rather than a
    one-day spike.
    """

    name: str
    day: date
    lag_days: int = 0
    decay: int = 0

    def window(self) -> list[date]:
        start = self.day + timedelta(days=self.lag_days)
        return [start + timedelta(days=i) for i in range(self.decay + 1)]


# Event vocabulary. Keeping this as an explicit list means the model's
# regressors are auditable by a planner who does not read Python: every
# named column in the forecast traces back to a line here.
EVENT_NAMES = (
    "annual_charges_notification",   # Feb: new charges land for the April year
    "april_tariff_change",           # 1 Apr: tariff takes effect
    "annual_bill_issue",             # main annual bill despatch
    "direct_debit_collection",       # monthly DD collection dates
    "meter_read_cycle",              # quarterly meter reading window
    "helpu_campaign",                # HelpU / WaterSure Wales affordability push
    "psr_campaign",                  # Priority Services Register outreach
    "freeze_thaw",                   # winter burst / supply interruption spike
    "storm_event",                   # sewer flooding and drainage contacts
    "dry_weather_spell",             # summer demand and pressure contacts
    "st_davids_day",                 # observance, mild Welsh volume effect
)


def retail_events(year: int) -> list[CalendarEvent]:
    """The dated Retail event set for a charging year.

    Dates are illustrative but structurally faithful to how a UK water
    company's charging year works: charges are notified in February, take
    effect on 1 April, and the bill despatch and direct-debit calendar
    follow from there.
    """
    ev: list[CalendarEvent] = []

    # Charges notification: posted mid-February, calls land 2 days later
    # and tail off over the following fortnight.
    ev.append(CalendarEvent("annual_charges_notification", date(year, 2, 12), lag_days=2, decay=12))

    # Tariff change bites on 1 April; the query wave runs about a week.
    ev.append(CalendarEvent("april_tariff_change", date(year, 4, 1), lag_days=0, decay=7))

    # Annual bill despatch in three waves so the contact centre is not hit
    # with the whole book at once - this is a planning lever in itself.
    for wave_day in (3, 10, 17):
        ev.append(CalendarEvent("annual_bill_issue", date(year, 4, wave_day), lag_days=2, decay=6))

    # Direct debit collection dates: the 1st, 8th, 15th and 25th of each
    # month. Failed payments and balance queries follow within two days.
    for month in range(1, 13):
        for dom in (1, 8, 15, 25):
            ev.append(CalendarEvent("direct_debit_collection", date(year, month, dom), lag_days=1, decay=2))

    # Quarterly meter reading windows.
    for month in (1, 4, 7, 10):
        ev.append(CalendarEvent("meter_read_cycle", date(year, month, 20), lag_days=0, decay=9))

    # Affordability and vulnerability campaigns. HelpU is Welsh Water's
    # social tariff; the Priority Services Register covers customers who
    # need extra support during an interruption. Both are deliberately
    # *demand-generating* - the business wants these calls.
    ev.append(CalendarEvent("helpu_campaign", date(year, 9, 15), lag_days=1, decay=20))
    ev.append(CalendarEvent("helpu_campaign", date(year, 1, 8), lag_days=1, decay=20))
    ev.append(CalendarEvent("psr_campaign", date(year, 10, 6), lag_days=1, decay=14))

    # Weather-driven operational events. Dated here for reproducibility;
    # in production these arrive from the operational feed and are the
    # main reason a same-day re-forecast exists at all.
    ev.append(CalendarEvent("freeze_thaw", date(year, 1, 17), lag_days=0, decay=5))
    ev.append(CalendarEvent("freeze_thaw", date(year, 12, 9), lag_days=0, decay=5))
    ev.append(CalendarEvent("storm_event", date(year, 11, 21), lag_days=0, decay=3))
    ev.append(CalendarEvent("storm_event", date(year, 2, 26), lag_days=0, decay=3))
    ev.append(CalendarEvent("dry_weather_spell", date(year, 7, 8), lag_days=0, decay=16))

    ev.append(CalendarEvent("st_davids_day", date(year, 3, 1), lag_days=0, decay=0))

    return ev


def event_flags(days: list[date]) -> dict[str, list[float]]:
    """Build the event regressor matrix over `days`.

    Returns one column per event name holding a decaying intensity in
    [0, 1]: 1.0 on the first affected day, tapering linearly across the
    decay window. Overlapping instances take the maximum rather than
    summing, so two direct-debit dates close together cannot manufacture
    an intensity the model has never seen.
    """
    index = {d: i for i, d in enumerate(days)}
    cols = {name: [0.0] * len(days) for name in EVENT_NAMES}

    years = sorted({d.year for d in days})
    for year in years:
        for event in retail_events(year):
            window = event.window()
            span = len(window)
            for step, d in enumerate(window):
                pos = index.get(d)
                if pos is None:
                    continue
                intensity = 1.0 - (step / span) if span > 1 else 1.0
                col = cols[event.name]
                if intensity > col[pos]:
                    col[pos] = intensity

    return cols
