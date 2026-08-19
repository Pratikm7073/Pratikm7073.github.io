"""Early-warning register: what will go wrong, and what to do about it.

The JD asks for the ability to "identify and highlight potential future
issues that could impact the business and propose mitigation to avoid
them". That is a different job from producing a plan, and it is the part
that gets a planner listened to. A gap in week 21 is not news in week 21.
It is news now, while there is still time to act, and only if it arrives
with a costed option attached.

Every risk raised here carries four things:

* **when** it bites, and when the last useful decision point is;
* **how big** it is, in FTE and in pounds;
* **whether it is still recoverable**, given recruitment lead times;
* **what to do**, specifically, with the saving quantified.

The recoverability test is the one that changes behaviour. A gap inside
the recruitment lead time cannot be hired for at any price, so raising it
as "we need to recruit" is useless advice. It has to be met with
overtime, leave re-profiling, deflection or accepted service degradation -
and the register says which.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta

import numpy as np
import pandas as pd

from .config import PlanConfig

__all__ = ["Risk", "build_risk_register", "leave_reprofiling_opportunity"]

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass
class Risk:
    """One entry in the early-warning register."""

    code: str
    severity: str
    title: str
    week: date | None
    impact_fte: float
    impact_cost: float
    recoverable: bool
    detail: str
    mitigation: str
    saving: float = 0.0
    tags: list[str] = field(default_factory=list)

    def as_row(self) -> dict:
        return {
            "code": self.code,
            "severity": self.severity,
            "title": self.title,
            "week": self.week,
            "impact_fte": round(self.impact_fte, 1),
            "impact_cost": round(self.impact_cost),
            "recoverable": "Yes" if self.recoverable else "No",
            "detail": self.detail,
            "mitigation": self.mitigation,
            "estimated_saving": round(self.saving),
        }


def leave_reprofiling_opportunity(weekly: pd.DataFrame, config: PlanConfig) -> tuple[float, float, list[date], list[date]]:
    """Quantify the leave that could be moved from peak weeks into troughs.

    This is the single cheapest lever a contact centre planner has and the
    one most often left on the table. Annual leave is roughly 11% of
    capacity and it is *fungible across the year*: every FTE-week of leave
    taken in a trough instead of a peak converts idle paid time into peak
    cover at no incremental cost at all.

    The constraint is that leave is granted months ahead, so this only
    works if the peak is identified early - which is exactly what a
    medium-term plan is for. Returned as a pair of week lists so the
    recommendation can name the weeks to close and the weeks to open.
    """
    surplus = weekly[weekly["gap_fte"] > 0]
    deficit = weekly[weekly["gap_fte"] < 0]
    if surplus.empty or deficit.empty:
        return 0.0, 0.0, [], []

    # Only leave that is actually *movable*: capped by the leave
    # entitlement embedded in each surplus week, not by the raw surplus.
    leave_share = config.shrinkage.annual_leave
    movable = float(np.minimum(
        surplus["gap_fte"].to_numpy(),
        surplus["required_fte"].to_numpy() * leave_share,
    ).sum())
    needed = float(-deficit["gap_fte"].sum())
    transferable = min(movable, needed)

    contracted = config.cost.contracted_hours_per_week
    rate = config.cost.advisor_hourly_cost
    # Saving is the premium avoided, not the whole cost: the hours are
    # paid either way, so moving leave saves the agency uplift only.
    saving = transferable * contracted * rate * (config.cost.agency_multiplier - 1.0)

    trough_weeks = list(surplus.nlargest(4, "gap_fte")["week_start"])
    peak_weeks = list(deficit.nsmallest(4, "gap_fte")["week_start"])
    return transferable, saving, trough_weeks, peak_weeks


def build_risk_register(
    plan,
    config: PlanConfig,
    coverage_floor: float = 0.97,
    agency_share_ceiling: float = 0.05,
) -> list[Risk]:
    """Scan a completed plan and raise everything worth escalating."""
    weekly = plan.weekly
    risks: list[Risk] = []

    supply = config.supply
    lead_weeks = supply.recruitment_lead_weeks + supply.training_weeks + supply.nesting_weeks
    contracted = config.cost.contracted_hours_per_week
    rate = config.cost.advisor_hourly_cost
    horizon_start = plan.start

    # ── 1. Weeks that miss coverage ──
    short = weekly[weekly["gap_fte"] < -0.5].copy()
    for row in short.itertuples():
        weeks_out = (row.week_start - horizon_start).days // 7
        recoverable = weeks_out >= lead_weeks
        gap = -float(row.gap_fte)
        cost = gap * contracted * rate * (config.cost.agency_multiplier - 1.0)
        severity = "critical" if gap > 40 else "high" if gap > 15 else "medium"

        if recoverable:
            mitigation = (
                f"Recruitable: a cohort starting by week {weeks_out - lead_weeks} "
                f"({(horizon_start + timedelta(weeks=max(0, weeks_out - lead_weeks))):%d %b}) "
                f"is productive in time. Approx {int(np.ceil(gap))} heads."
            )
        else:
            mitigation = (
                "Inside the recruitment lead time - cannot be hired for. "
                "Close with leave re-profiling, overtime, temporary "
                "cross-skilling from a covered queue, and proactive "
                "deflection of billing contacts to self-serve."
            )

        risks.append(Risk(
            code=f"GAP-{row.week_start:%Y%m%d}",
            severity=severity,
            title=f"Resource shortfall of {gap:.0f} FTE",
            week=row.week_start,
            impact_fte=gap,
            impact_cost=cost,
            recoverable=recoverable,
            detail=(
                f"Week commencing {row.week_start:%d %b %Y} requires "
                f"{row.required_fte:.0f} FTE against a projected supply of "
                f"{row.supply_fte:.0f} FTE ({row.coverage_pct:.0f}% coverage). "
                f"This is {weeks_out} weeks out; the recruitment pipeline is "
                f"{lead_weeks} weeks."
            ),
            mitigation=mitigation,
            tags=["capacity", "recruitment" if recoverable else "in-year"],
        ))

    # ── 2. Reliance on agency cover ──
    total_hours = float((weekly["supply_fte"] * contracted).sum())
    agency_hours = float(weekly["agency_hours"].sum())
    if total_hours > 0 and agency_hours / total_hours > agency_share_ceiling:
        share = agency_hours / total_hours
        premium = float(weekly["agency_cost"].sum()) - agency_hours * rate
        risks.append(Risk(
            code="AGENCY-RELIANCE",
            severity="high",
            title=f"Agency cover at {share:.1%} of contracted hours",
            week=None,
            impact_fte=agency_hours / contracted,
            impact_cost=premium,
            recoverable=True,
            detail=(
                f"{agency_hours:,.0f} agency hours across the horizon, carrying a "
                f"premium of GBP {premium:,.0f} over substantive cost. Agency "
                f"advisors also carry lower first-contact resolution while they "
                f"learn the billing system, so the true cost exceeds the rate card."
            ),
            mitigation=(
                "Bring forward the recruitment cohorts identified in the intake "
                "plan and convert the highest-performing agency advisors to "
                "substantive contracts, which removes the premium and retains "
                "the training investment."
            ),
            tags=["cost"],
        ))

    # ── 3. Leave re-profiling opportunity ──
    movable, saving, troughs, peaks = leave_reprofiling_opportunity(weekly, config)
    if movable > 1.0:
        risks.append(Risk(
            code="LEAVE-PROFILE",
            severity="medium",
            title=f"{movable:.0f} FTE-weeks of leave sitting in the wrong weeks",
            week=peaks[0] if peaks else None,
            impact_fte=movable,
            impact_cost=0.0,
            recoverable=True,
            detail=(
                "The plan carries substantial surplus in the festive and "
                "shoulder weeks while the January peak runs short. Annual leave "
                "is roughly "
                f"{config.shrinkage.annual_leave:.0%} of capacity and is fungible "
                "across the year, so this is capacity that already exists in the "
                "wrong place rather than capacity that has to be bought."
            ),
            mitigation=(
                "Restrict leave in "
                + ", ".join(f"w/c {w:%d %b}" for w in peaks[:3])
                + " and actively promote it in "
                + ", ".join(f"w/c {w:%d %b}" for w in troughs[:3])
                + ". Needs to be agreed with Operations before the leave window "
                "opens, which is the reason this is raised now rather than in December."
            ),
            saving=saving,
            tags=["cost", "shrinkage", "no-cost-lever"],
        ))

    # ── 4. Structural over-supply in the festive trough ──
    idle = weekly.nlargest(1, "gap_fte")
    if not idle.empty:
        row = idle.iloc[0]
        if row["gap_fte"] > 0.25 * row["required_fte"]:
            idle_cost = float(row["gap_fte"]) * contracted * rate
            risks.append(Risk(
                code="IDLE-TROUGH",
                severity="medium",
                title=f"{row['gap_fte']:.0f} FTE surplus in w/c {row['week_start']:%d %b}",
                week=row["week_start"],
                impact_fte=float(row["gap_fte"]),
                impact_cost=idle_cost,
                recoverable=True,
                detail=(
                    f"Demand falls to {row['required_fte']:.0f} FTE against "
                    f"{row['supply_fte']:.0f} available - a paid surplus of "
                    f"GBP {idle_cost:,.0f} in a single week."
                ),
                mitigation=(
                    "Schedule the January training and coaching programme into "
                    "this week, run the annual compliance refresh, and open leave. "
                    "Converting idle capacity into training capacity removes it "
                    "from January's shrinkage, where it is far more expensive."
                ),
                saving=idle_cost * 0.45,
                tags=["cost", "shrinkage"],
            ))

    # ── 5. Forecast accuracy risk on the lines that matter ──
    if plan.selection:
        weak = [
            s for s in plan.selection.values()
            if s.chosen_wape > 20.0 or not s.beats_baseline
        ]
        if weak:
            worst = max(weak, key=lambda s: s.chosen_wape)
            risks.append(Risk(
                code="FORECAST-CONFIDENCE",
                severity="medium",
                title=f"{len(weak)} service line(s) forecasting above 20% WAPE",
                week=None,
                impact_fte=0.0,
                impact_cost=0.0,
                recoverable=True,
                detail=(
                    f"Worst is {worst.line_key} at {worst.chosen_wape:.1f}% WAPE "
                    f"against a naive baseline of {worst.baseline_wape:.1f}%. These "
                    "are low-volume deferrable queues where day-to-day variation is "
                    "genuinely large relative to the mean, so the error is partly "
                    "irreducible rather than a modelling failure."
                ),
                mitigation=(
                    "Plan these lines at weekly rather than daily granularity, "
                    "where the error partially cancels, and hold a shared "
                    "contingency pool rather than staffing each queue to its own "
                    "peak. Revisit if volumes grow enough to support daily planning."
                ),
                tags=["forecast"],
            ))

    # ── 6. Single-skill concentration on the Welsh language line ──
    welsh = [line for line in config.service_lines if line.welsh_language]
    if welsh:
        risks.append(Risk(
            code="WELSH-SKILL-POOL",
            severity="high",
            title="Welsh-language cover has no economies of scale",
            week=None,
            impact_fte=0.0,
            impact_cost=0.0,
            recoverable=True,
            detail=(
                "The Cymraeg line runs at roughly "
                f"{welsh[0].base_daily_volume:.0f} contacts a day. At that volume "
                "Erlang requires proportionally far more headcount per contact "
                "than the main voice queue - a small queue cannot pool its "
                "variance - and the skill cannot be covered by overtime from the "
                "wider floor. A single unplanned absence is a service level "
                "failure on a line customers are entitled to expect."
            ),
            mitigation=(
                "Hold a minimum of two Welsh-speaking advisors rostered in every "
                "open interval regardless of the Erlang result, cross-skill Welsh "
                "speakers across billing and operations so the pool is larger than "
                "the queue, and track this line's service level separately rather "
                "than inside the blended voice figure where it will disappear."
            ),
            tags=["service", "welsh-language", "resilience"],
        ))

    risks.sort(key=lambda r: (SEVERITY_ORDER.get(r.severity, 9), -(r.impact_cost or 0)))
    return risks
