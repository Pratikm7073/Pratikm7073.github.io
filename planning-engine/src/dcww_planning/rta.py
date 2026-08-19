"""Real Time Analysis: in-day re-forecasting, adherence and exceptions.

The plan is built weeks out. The day still goes wrong. Real Time Analysis
is the discipline of noticing that early enough to do something, and it
answers three questions in order:

1. **Is today tracking to forecast?** If the morning has run 12% hot, how
   much of that carries into the afternoon?
2. **Are the people who were rostered actually on the phone?** Schedule
   adherence and off-line exceptions.
3. **Given both, what will service level land at, and what is the
   cheapest intervention that fixes it?**

The re-forecast is deliberately **damped**, and that is the module's most
important line. Intraday variance is largely noise: an hour that runs 20%
above forecast is usually a busy hour, not the first hour of a 20% day. An
undamped re-forecast chases that noise, and an RTA desk that reacts to
every wobble burns its credibility and its overtime budget by ten in the
morning. Damping expresses the real relationship - some of a morning
variance persists, most of it does not - and the damping factor rises as
the day progresses and the evidence accumulates.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np

from .config import INTERVAL_MINUTES, INTERVALS_PER_DAY, ChannelSpec
from .erlang import service_level, staff_required

__all__ = [
    "IntradayPosition", "reforecast_intraday", "AdherenceResult",
    "schedule_adherence", "project_service_level", "recommend_actions",
]


@dataclass
class IntradayPosition:
    """Where today stands, and where it is heading."""

    day: date
    line_key: str
    elapsed_intervals: int
    actual_so_far: float
    expected_so_far: float
    variance_pct: float
    original_day_forecast: float
    revised_day_forecast: float
    revised_remaining: np.ndarray
    damping_applied: float

    @property
    def revision_pct(self) -> float:
        if self.original_day_forecast <= 0:
            return 0.0
        return (self.revised_day_forecast / self.original_day_forecast - 1.0) * 100


def reforecast_intraday(
    day: date,
    line_key: str,
    profile: np.ndarray,
    day_forecast: float,
    actuals: np.ndarray,
    elapsed_intervals: int,
    base_damping: float = 0.35,
    max_damping: float = 0.85,
) -> IntradayPosition:
    """Revise the rest of the day from what has arrived so far.

    The damping factor scales with how much of the day is complete:

        damping = base + (max - base) * share_of_day_elapsed

    At 09:00 a variance is mostly noise and is barely acted on; by 14:00
    the same variance is largely signal and is carried through almost in
    full. A fixed damping factor is wrong at both ends of the day - too
    twitchy in the morning, too slow in the afternoon.
    """
    profile = np.asarray(profile, dtype=float)
    actuals = np.asarray(actuals, dtype=float)
    elapsed = int(np.clip(elapsed_intervals, 0, INTERVALS_PER_DAY))

    expected_so_far = float(profile[:elapsed].sum()) * day_forecast
    actual_so_far = float(actuals[:elapsed].sum())

    share_elapsed = float(profile[:elapsed].sum())
    damping = base_damping + (max_damping - base_damping) * share_elapsed

    if expected_so_far > 0:
        ratio = actual_so_far / expected_so_far
        variance_pct = (ratio - 1.0) * 100
        adjustment = 1.0 + damping * (ratio - 1.0)
    else:
        variance_pct = 0.0
        adjustment = 1.0

    remaining_profile = profile.copy()
    remaining_profile[:elapsed] = 0.0
    revised_remaining = remaining_profile * day_forecast * adjustment

    return IntradayPosition(
        day=day, line_key=line_key, elapsed_intervals=elapsed,
        actual_so_far=actual_so_far, expected_so_far=expected_so_far,
        variance_pct=variance_pct,
        original_day_forecast=float(day_forecast),
        revised_day_forecast=actual_so_far + float(revised_remaining.sum()),
        revised_remaining=revised_remaining,
        damping_applied=damping,
    )


@dataclass
class AdherenceResult:
    """Schedule adherence and where the lost time went."""

    scheduled_hours: float
    actual_hours: float
    adherence_pct: float
    conformance_pct: float
    understaffed_hours: float
    overstaffed_hours: float
    worst_intervals: list[tuple[str, float]]

    def as_row(self) -> dict:
        return {
            "scheduled_hours": round(self.scheduled_hours, 1),
            "actual_hours": round(self.actual_hours, 1),
            "adherence_pct": round(self.adherence_pct, 2),
            "conformance_pct": round(self.conformance_pct, 2),
            "understaffed_hours": round(self.understaffed_hours, 1),
            "overstaffed_hours": round(self.overstaffed_hours, 1),
        }


def schedule_adherence(scheduled: np.ndarray, actual: np.ndarray, top_n: int = 5) -> AdherenceResult:
    """Adherence and conformance - two different things, routinely confused.

    * **Adherence** asks whether people were on the phone *when they were
      scheduled to be*. It caps the credit at the scheduled level, so
      being over-staffed at 11:00 cannot offset being short at 15:00.
      This is the measure that predicts service level.
    * **Conformance** asks only whether the total hours worked matched the
      total scheduled. It nets the two off.

    An operation can run 100% conformance and 78% adherence - everybody
    worked their hours, just not at the times the queue needed them - and
    that combination is one of the most common causes of a service level
    that misses despite the headcount being right. Reporting only
    conformance hides it completely.
    """
    scheduled = np.asarray(scheduled, dtype=float)
    actual = np.asarray(actual, dtype=float)
    hours = INTERVAL_MINUTES / 60.0

    scheduled_hours = float(scheduled.sum()) * hours
    actual_hours = float(actual.sum()) * hours

    in_adherence = float(np.minimum(scheduled, actual).sum()) * hours
    adherence = in_adherence / scheduled_hours * 100 if scheduled_hours > 0 else 100.0
    conformance = actual_hours / scheduled_hours * 100 if scheduled_hours > 0 else 100.0

    shortfall = np.maximum(scheduled - actual, 0.0)
    surplus = np.maximum(actual - scheduled, 0.0)

    order = np.argsort(-shortfall)[:top_n]
    worst = [
        (f"{int(i) * INTERVAL_MINUTES // 60:02d}:{int(i) * INTERVAL_MINUTES % 60:02d}",
         round(float(shortfall[i]), 2))
        for i in order if shortfall[i] > 0
    ]

    return AdherenceResult(
        scheduled_hours=scheduled_hours,
        actual_hours=actual_hours,
        adherence_pct=adherence,
        conformance_pct=conformance,
        understaffed_hours=float(shortfall.sum()) * hours,
        overstaffed_hours=float(surplus.sum()) * hours,
        worst_intervals=worst,
    )


def project_service_level(
    contacts: np.ndarray,
    staffed: np.ndarray,
    channel: ChannelSpec,
    aht_seconds: float,
) -> np.ndarray:
    """Service level each interval will deliver at current staffing."""
    contacts = np.asarray(contacts, dtype=float)
    staffed = np.asarray(staffed, dtype=float)
    out = np.ones(len(contacts))
    interval_seconds = INTERVAL_MINUTES * 60.0

    for i, (volume, agents) in enumerate(zip(contacts, staffed)):
        if volume <= 0:
            continue
        traffic = volume * aht_seconds / interval_seconds / max(channel.concurrency, 1e-9)
        out[i] = service_level(traffic, int(np.floor(agents)), aht_seconds,
                               channel.service_level_seconds)
    return out


def recommend_actions(
    contacts: np.ndarray,
    staffed: np.ndarray,
    channel: ChannelSpec,
    aht_seconds: float,
    from_interval: int = 0,
) -> list[dict]:
    """Cheapest intervention per at-risk interval, in escalation order.

    The order is not arbitrary - it is cheapest first, and it is the order
    an RTA desk actually works through:

    1. **Move off-line activity.** Deferring a coaching session or a team
       meeting costs nothing but goodwill and recovers capacity in the
       same interval.
    2. **Delay or shorten breaks.** Free, but limited and unpopular, and
       it just moves the problem later in the day.
    3. **Cross-skill from a healthy queue.** Free if another queue is
       genuinely over-covered, which the same calculation can confirm.
    4. **Overtime.** Costs the overtime premium, and needs enough notice
       that it stops being an in-day lever after about lunchtime.

    Only intervals actually missing target are returned, so the output is
    a short action list rather than a report to be read.
    """
    projected = project_service_level(contacts, staffed, channel, aht_seconds)
    interval_seconds = INTERVAL_MINUTES * 60.0
    actions: list[dict] = []

    for i in range(from_interval, len(contacts)):
        volume = float(contacts[i])
        if volume <= 0 or projected[i] >= channel.service_level_target:
            continue

        needed = staff_required(
            contacts=volume, aht_seconds=aht_seconds,
            interval_seconds=interval_seconds,
            sl_target=channel.service_level_target,
            sl_seconds=channel.service_level_seconds,
            max_occupancy=channel.max_occupancy,
            concurrency=channel.concurrency,
        ).agents_required
        deficit = needed - float(staffed[i])
        if deficit <= 0.5:
            continue

        if deficit <= 2:
            lever = "Release off-line activity (coaching, 1-2-1s) in this interval"
        elif deficit <= 5:
            lever = "Re-time breaks and release off-line activity"
        elif deficit <= 12:
            lever = "Cross-skill from an over-covered queue, then re-time breaks"
        else:
            lever = "Overtime call-out required - beyond in-day levers"

        actions.append({
            "interval": int(i),
            "interval_start": f"{i * INTERVAL_MINUTES // 60:02d}:{i * INTERVAL_MINUTES % 60:02d}",
            "contacts": round(volume, 1),
            "staffed": round(float(staffed[i]), 1),
            "required": round(needed, 1),
            "deficit_fte": round(deficit, 1),
            "projected_sl": round(float(projected[i]), 3),
            "recommended_action": lever,
        })

    return actions
