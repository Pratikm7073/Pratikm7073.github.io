"""From forecast contacts to rostered people.

Four steps, each of which is somewhere a plan usually goes wrong:

1. **Spread the day across intervals.** A daily total is not a plan. Two
   thousand calls spread evenly across a ten-hour day needs far fewer
   advisors than the same two thousand with a mid-morning peak, because
   Erlang is convex - the peak interval drives the roster and the quiet
   ones cannot give the capacity back.

2. **Size each interval.** Erlang C for interactive channels, workload
   arithmetic for deferrable ones. See `erlang.py`.

3. **Apply shrinkage.** Divide, never multiply. Requiring 100 advisors on
   the phone at 27.8% shrinkage means rostering 100 / (1 - 0.278) = 138.5,
   not 100 * 1.278 = 127.8. The multiply-instead-of-divide error is
   endemic, always under-staffs, and here would lose eleven FTE.

4. **Cover it with shifts.** Interval requirements are not a roster.
   Turning a sawtooth requirement curve into whole shifts that people can
   actually work is where theoretical capacity meets the working time
   agreement, and it always costs more than the raw requirement implies.

Supply is modelled separately: attrition erodes headcount every week, and
recruitment replaces it only after a lead time plus training plus nesting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np

from .config import INTERVAL_MINUTES, INTERVALS_PER_DAY, PlanConfig, ServiceLine
from .erlang import deferrable_fte, staff_required

__all__ = [
    "IntervalPlan", "build_interval_plan", "rostered_from_on_phone",
    "Shift", "generate_shift_patterns", "cover_day", "DayRoster",
    "SupplyWeek", "supply_plan", "recruitment_plan",
]


# ─────────────────────────────────────────────────────────────────────
# Interval requirements
# ─────────────────────────────────────────────────────────────────────

@dataclass
class IntervalPlan:
    """Half-hourly requirement for one line on one day."""

    day: date
    line_key: str
    channel: str
    intervals: np.ndarray            # index 0..47
    contacts: np.ndarray
    on_phone_required: np.ndarray    # before shrinkage
    rostered_required: np.ndarray    # after shrinkage
    service_level: np.ndarray
    occupancy: np.ndarray
    binding: list[str]

    def total_contacts(self) -> float:
        return float(self.contacts.sum())

    def peak_rostered(self) -> float:
        return float(self.rostered_required.max()) if len(self.rostered_required) else 0.0

    def rostered_hours(self) -> float:
        return float(self.rostered_required.sum()) * (INTERVAL_MINUTES / 60.0)


def rostered_from_on_phone(on_phone: float | np.ndarray, shrinkage_total: float):
    """Gross a requirement up for shrinkage.

    Divide by (1 - shrinkage), never multiply by (1 + shrinkage). At 27.8%
    shrinkage the two differ by about 8% of headcount, always in the
    direction of under-staffing, and the mistake is invisible in a
    spreadsheet because both produce a plausible-looking number.
    """
    if shrinkage_total >= 1.0:
        raise ValueError("shrinkage must be below 100%")
    return on_phone / (1.0 - shrinkage_total)


def build_interval_plan(
    day: date,
    line: ServiceLine,
    daily_contacts: float,
    profile: np.ndarray,
    config: PlanConfig,
    aht_seconds: float | None = None,
) -> IntervalPlan:
    """Size every open interval of one day for one service line."""
    channel = config.channel(line.channel)
    aht = aht_seconds if aht_seconds is not None else channel.aht_seconds * line.aht_multiplier
    shrinkage = config.shrinkage.total

    contacts = np.asarray(profile, dtype=float) * float(daily_contacts)
    open_intervals = np.nonzero(np.asarray(profile) > 0)[0]

    on_phone = np.zeros(INTERVALS_PER_DAY)
    sl = np.zeros(INTERVALS_PER_DAY)
    occ = np.zeros(INTERVALS_PER_DAY)
    binding = ["closed"] * INTERVALS_PER_DAY

    if channel.kind == "interactive":
        for i in open_intervals:
            req = staff_required(
                contacts=contacts[i],
                aht_seconds=aht,
                interval_seconds=INTERVAL_MINUTES * 60.0,
                sl_target=channel.service_level_target,
                sl_seconds=channel.service_level_seconds,
                max_occupancy=channel.max_occupancy,
                concurrency=channel.concurrency,
            )
            on_phone[i] = req.agents_required
            sl[i] = req.service_level
            occ[i] = req.occupancy
            binding[i] = req.binding_constraint
    else:
        # Deferrable work is levelled across the open window rather than
        # chased interval by interval. Chasing a deferrable arrival curve
        # is the mistake that makes email look as expensive as voice: the
        # whole point of a 24-hour SLA is that the peak does not have to
        # be staffed for.
        open_hours = len(open_intervals) * (INTERVAL_MINUTES / 60.0)
        total_fte = deferrable_fte(
            contacts=float(contacts.sum()),
            aht_seconds=aht,
            available_hours=open_hours,
            productive_utilisation=channel.productive_utilisation,
        )
        for i in open_intervals:
            on_phone[i] = total_fte
            occ[i] = channel.productive_utilisation
            sl[i] = 1.0
            binding[i] = "workload"

    return IntervalPlan(
        day=day,
        line_key=line.key,
        channel=line.channel,
        intervals=np.arange(INTERVALS_PER_DAY),
        contacts=contacts,
        on_phone_required=on_phone,
        rostered_required=rostered_from_on_phone(on_phone, shrinkage),
        service_level=sl,
        occupancy=occ,
        binding=binding,
    )


# ─────────────────────────────────────────────────────────────────────
# Shift covering
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Shift:
    """A workable shift pattern, in half-hour interval indices."""

    start: int
    length_intervals: int
    break_offset: int          # intervals from start to the unpaid break
    break_intervals: int = 1

    @property
    def end(self) -> int:
        return self.start + self.length_intervals

    def coverage(self) -> np.ndarray:
        """1.0 where this shift puts someone on the phone, 0 elsewhere."""
        cover = np.zeros(INTERVALS_PER_DAY)
        for i in range(self.start, min(self.end, INTERVALS_PER_DAY)):
            cover[i] = 1.0
        for b in range(self.break_intervals):
            idx = self.start + self.break_offset + b
            if idx < INTERVALS_PER_DAY:
                cover[idx] = 0.0
        return cover

    def label(self) -> str:
        def hhmm(i: int) -> str:
            m = i * INTERVAL_MINUTES
            return f"{m // 60:02d}:{m % 60:02d}"
        return f"{hhmm(self.start)}-{hhmm(min(self.end, INTERVALS_PER_DAY - 1))}"


def generate_shift_patterns(
    earliest: int = 0,
    latest_end: int = INTERVALS_PER_DAY,
    lengths: tuple[int, ...] = (8, 12, 16, 18, 20),   # 4h, 6h, 8h, 9h, 10h
    start_step: int = 1,
) -> list[Shift]:
    """Candidate shifts on a half-hour grid, inside a trading window.

    Two choices here are worth defending.

    **Start times step every half hour**, not every hour. Hourly starts
    are tidier to administer and measurably more expensive: a requirement
    that ramps steeply between 08:00 and 10:00 cannot be tracked by hourly
    starts without over-covering half of every hour.

    **Part-time lengths are included.** A contact centre requirement curve
    is double-humped, and covering a four-hour morning peak with
    eight-hour shifts means paying for four hours of trough. Four- and
    six-hour patterns are how UK contact centres actually cover peaks, and
    excluding them costs roughly fifteen points of roster efficiency.

    Shifts under six hours carry no unpaid break, matching the UK rest
    break entitlement, which applies to work beyond six hours.
    """
    patterns: list[Shift] = []
    for length in lengths:
        for start in range(earliest, latest_end - length + 1, start_step):
            patterns.append(Shift(
                start=start,
                length_intervals=length,
                break_offset=length // 2,
                break_intervals=1 if length > 12 else 0,
            ))
    return patterns


@dataclass
class DayRoster:
    """A set of shifts covering (most of) one day's requirement."""

    day: date
    shifts: dict[Shift, int] = field(default_factory=dict)
    requirement: np.ndarray = field(default_factory=lambda: np.zeros(INTERVALS_PER_DAY))
    coverage: np.ndarray = field(default_factory=lambda: np.zeros(INTERVALS_PER_DAY))

    @property
    def headcount(self) -> int:
        return int(sum(self.shifts.values()))

    @property
    def scheduled_hours(self) -> float:
        return float(self.coverage.sum()) * (INTERVAL_MINUTES / 60.0)

    @property
    def required_hours(self) -> float:
        return float(self.requirement.sum()) * (INTERVAL_MINUTES / 60.0)

    @property
    def over_cover_hours(self) -> float:
        return float(np.maximum(self.coverage - self.requirement, 0).sum()) * (INTERVAL_MINUTES / 60.0)

    @property
    def under_cover_hours(self) -> float:
        return float(np.maximum(self.requirement - self.coverage, 0).sum()) * (INTERVAL_MINUTES / 60.0)

    @property
    def efficiency(self) -> float:
        """Required hours over scheduled hours.

        Never reaches 1.0 and should not be expected to. Whole shifts
        cannot trace a sawtooth requirement curve, so some over-cover is
        structural rather than wasteful. Anything above roughly 0.85 is a
        good roster; chasing 0.95 means split shifts and unhappy people.
        """
        return self.required_hours / self.scheduled_hours if self.scheduled_hours else 0.0


def cover_day(
    day: date,
    requirement: np.ndarray,
    patterns: list[Shift] | None = None,
    max_shifts: int = 600,
    part_time_share_cap: float = 0.35,
    part_time_below: int = 16,
) -> DayRoster:
    """Greedily cover an interval requirement curve with whole shifts.

    Shift scheduling is a set-covering problem and is NP-hard in general.
    A greedy heuristic - repeatedly add whichever shift removes the most
    remaining deficit - is the standard practical answer and typically
    lands within a few per cent of optimal on curves this shape. It also
    has the property that matters operationally: it never invents a
    pattern nobody can work.

    The greedy step is deliberately weighted by *remaining* deficit rather
    than by raw coverage, so a shift that covers a half-hour already
    fully staffed scores nothing for it.

    `part_time_share_cap` is the constraint that keeps the answer real.
    Left to optimise freely, the greedy covers a double-humped curve
    almost entirely with four-hour shifts - it is genuinely the cheapest
    cover, and it is a roster nobody can hire for. Capping part-time hours
    at a recruitable share costs a few points of efficiency and produces a
    shift mix an operation can actually staff. It is a judgement call, and
    it is a parameter rather than a constant so it can be argued about
    with the resourcing team rather than buried.
    """
    requirement = np.asarray(requirement, dtype=float)

    trading = np.nonzero(requirement > 0)[0]
    if len(trading) == 0:
        return DayRoster(day=day, requirement=requirement, coverage=np.zeros(INTERVALS_PER_DAY))

    if patterns is None:
        # Confine shifts to the trading window. Without this the greedy
        # happily books an 03:00 start to pick up the 08:00 ramp, because
        # the hours before opening cost it nothing in a pure
        # coverage-maximising score - and every one of them is paid.
        patterns = generate_shift_patterns(
            earliest=int(trading[0]),
            latest_end=int(trading[-1]) + 1,
        )
    if not patterns:
        patterns = generate_shift_patterns()

    coverage = np.zeros(INTERVALS_PER_DAY)
    chosen: dict[Shift, int] = {}
    covers = {shift: shift.coverage() for shift in patterns}
    cost = {shift: float(cover.sum()) for shift, cover in covers.items()}
    part_time_hours = 0.0
    total_hours = 0.0

    for _ in range(max_shifts):
        deficit = np.maximum(requirement - coverage, 0.0)
        if deficit.sum() <= 0.5:
            break
        best_shift, best_score, best_gain = None, 0.0, 0.0
        for shift, cover in covers.items():
            gain = float(np.minimum(cover, deficit).sum())
            if gain <= 1e-9:
                continue
            if shift.length_intervals < part_time_below:
                projected = (part_time_hours + cost[shift]) / max(total_hours + cost[shift], 1e-9)
                if projected > part_time_share_cap:
                    continue
            # Score by useful hours per paid hour, not by raw coverage.
            # A ten-hour shift that fills six hours of deficit is worse
            # value than a four-hour shift that fills three, and a greedy
            # that maximises raw gain picks the long one every time.
            score = gain / cost[shift]
            if score > best_score:
                best_shift, best_score, best_gain = shift, score, gain
        if best_shift is None:
            break
        coverage += covers[best_shift]
        chosen[best_shift] = chosen.get(best_shift, 0) + 1
        total_hours += cost[best_shift]
        if best_shift.length_intervals < part_time_below:
            part_time_hours += cost[best_shift]

    return DayRoster(day=day, shifts=chosen, requirement=requirement, coverage=coverage)


# ─────────────────────────────────────────────────────────────────────
# Supply: attrition and the recruitment pipeline
# ─────────────────────────────────────────────────────────────────────

@dataclass
class SupplyWeek:
    """Headcount position for one week."""

    week_start: date
    opening_fte: float
    leavers: float
    in_training: float
    nesting: float
    productive_fte: float
    intake: int

    def as_row(self) -> dict:
        return {
            "week_start": self.week_start,
            "opening_fte": round(self.opening_fte, 1),
            "leavers": round(self.leavers, 2),
            "in_training": round(self.in_training, 1),
            "nesting": round(self.nesting, 1),
            "productive_fte": round(self.productive_fte, 1),
            "intake": self.intake,
        }


def supply_plan(
    config: PlanConfig,
    start_week: date,
    weeks: int,
    intake_by_week: dict[int, int] | None = None,
) -> list[SupplyWeek]:
    """Project available FTE week by week.

    Two things this captures that a flat headcount assumption does not,
    and both of them bite in the same direction:

    * **Attrition compounds.** It applies to a shrinking base, so a 23.5%
      annual rate is not 0.45% a week.
    * **Recruits are not capacity.** They are a cost for `training_weeks`,
      partial capacity for `nesting_weeks`, and only then a full advisor.
      A cohort hired to cover February must start in the previous
      November. Plans that credit new starters from their start date show
      a surplus in exactly the weeks the operation is actually short.
    """
    supply = config.supply
    intake_by_week = intake_by_week or {}
    weekly_attrition = supply.weekly_attrition
    pipeline_weeks = supply.training_weeks + supply.nesting_weeks

    productive = supply.opening_fte
    cohorts: list[list] = []                   # [start week, remaining size]
    rows: list[SupplyWeek] = []

    for w in range(weeks):
        opening = productive
        intake = int(intake_by_week.get(w, 0))
        if intake:
            cohorts.append([w, float(intake)])

        # Attrition hits productive advisors and trainees alike.
        leavers = productive * weekly_attrition
        productive -= leavers
        for cohort in cohorts:
            cohort[1] *= (1.0 - weekly_attrition)

        in_training = 0.0
        nesting = 0.0
        graduating = 0.0
        remaining: list[list] = []
        for cohort in cohorts:
            age = w - cohort[0]
            if age < supply.training_weeks:
                in_training += cohort[1]
                remaining.append(cohort)
            elif age < pipeline_weeks:
                nesting += cohort[1]
                remaining.append(cohort)
            else:
                graduating += cohort[1]
        cohorts = remaining
        productive += graduating

        rows.append(SupplyWeek(
            week_start=start_week + timedelta(weeks=w),
            opening_fte=opening,
            leavers=leavers,
            in_training=in_training,
            nesting=nesting,
            # Nesting advisors count at reduced productivity, not zero and
            # not one. They are on the floor taking contacts, just slowly.
            productive_fte=productive + nesting * supply.nesting_productivity,
            intake=intake,
        ))

    return rows


def recruitment_plan(
    config: PlanConfig,
    start_week: date,
    required_fte_by_week: list[float],
) -> dict[int, int]:
    """Work out an intake schedule that closes the projected gap.

    Walks the horizon forward, and whenever a shortfall appears, books an
    intake far enough in advance for it to be productive by then - lead
    time plus training plus nesting. Where that start date is already in
    the past the shortfall is reported rather than papered over: no
    recruitment decision taken today can staff next week, and a plan that
    pretends otherwise is worse than one that says "this gap will be
    covered by overtime or not at all".
    """
    supply = config.supply
    lead = supply.recruitment_lead_weeks + supply.training_weeks + supply.nesting_weeks
    weeks = len(required_fte_by_week)
    intake: dict[int, int] = {}

    # Each booked intake changes the projection for every later week, so
    # the schedule has to be re-derived rather than computed in one pass.
    # One gap is closed per iteration and the horizon is re-projected;
    # the budget is generous because a stalled loop would silently
    # under-recruit, which is the failure mode this whole function exists
    # to prevent.
    for _ in range(len(required_fte_by_week) * 4 + 20):
        projection = supply_plan(config, start_week, weeks, intake)
        added = False
        for w, required in enumerate(required_fte_by_week):
            gap = required - projection[w].productive_fte
            if gap <= 0.5:
                continue
            latest = w - lead
            if latest < 0:
                continue            # unrecoverable within the horizon

            # Book as late as possible, because a head hired earlier than
            # needed is paid for longer. If the ideal week is already at
            # capacity, walk *backwards* and hire sooner rather than
            # abandoning the gap - starting a cohort two weeks early
            # costs two weeks of salary, whereas not starting it at all
            # costs a quarter of agency cover at 1.5x the rate.
            for book_at in range(latest, -1, -1):
                # The intake cap is a monthly hiring capacity - classroom
                # space, trainer availability, how many offers the
                # resourcing team can actually land - so it is enforced
                # over a rolling four weeks. Applying a monthly number to
                # a single week silently quadruples hiring capacity, and
                # the plan then shows a gap closing that the business has
                # no way to close.
                window = sum(intake.get(x, 0) for x in range(max(0, book_at - 3), book_at + 1))
                room = supply.max_intake_per_month - window
                if room <= 0:
                    continue
                intake[book_at] = intake.get(book_at, 0) + int(min(room, np.ceil(gap)))
                added = True
                break
            if added:
                break
        if not added:
            break

    return intake
