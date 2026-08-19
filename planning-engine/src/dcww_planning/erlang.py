"""Queueing models: how many advisors an interval actually needs.

Three calculations, applied to different things on purpose:

* **Erlang C** for interactive channels. The industry standard, and what
  every WFM platform uses to size a half-hour. It assumes Poisson
  arrivals, exponential handle times, and - importantly - infinitely
  patient customers who never hang up.

* **Erlang A** for the abandonment question. Erlang A adds a patience
  parameter, so callers leave the queue. That single change matters more
  than it sounds: because Erlang C assumes nobody ever abandons, every
  caller must eventually be served, so the model demands enough agents to
  clear a queue that in reality partly clears itself. **Erlang C
  systematically over-staffs busy intervals.** Quantifying that gap is
  one of the clearest cost-saving arguments a planner can put in front of
  an operations director, which is why it is built in rather than left as
  an exercise.

* **Deferrable workload** for email, messaging and back office. These do
  not queue in the Erlang sense at all - they are a stock to be worked
  down against an SLA measured in hours. Running Erlang C on an email
  queue is a common and expensive mistake: it sizes for instant answer
  and can easily double the requirement.

Everything here is per-interval and stateless. Shrinkage, supply and
scheduling are applied downstream in `capacity.py`, so the queueing
mathematics stays testable in isolation against published tables.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "erlang_b", "erlang_c", "IntervalRequirement", "service_level",
    "average_speed_of_answer", "staff_required", "ErlangAResult",
    "erlang_a", "staff_required_erlang_a", "deferrable_fte",
]

MAX_AGENTS = 2000


# ─────────────────────────────────────────────────────────────────────
# Erlang B / C
# ─────────────────────────────────────────────────────────────────────

def erlang_b(traffic: float, agents: int) -> float:
    """Erlang B blocking probability, by the reciprocal recursion.

    The textbook form of Erlang B involves `traffic ** agents / agents!`,
    which overflows for any realistic contact centre - a hundred agents
    and eighty Erlangs puts both terms far beyond a float. The reciprocal
    recursion below is algebraically identical and never leaves a range
    a float can hold:

        1 / B(n) = 1 + n / (traffic * B(n-1))

    Erlang C is derived from B rather than computed directly for exactly
    the same reason.
    """
    if traffic <= 0:
        return 0.0
    if agents <= 0:
        return 1.0

    inverse = 1.0
    for n in range(1, int(agents) + 1):
        inverse = 1.0 + inverse * n / traffic
    return 1.0 / inverse


def erlang_c(traffic: float, agents: int) -> float:
    """Probability that an arriving contact has to wait at all.

    Derived from Erlang B:  C = B / (1 - rho*(1 - B)),  rho = traffic/agents.

    Returns 1.0 when the offered load meets or exceeds the number of
    agents. That is not a rounding convenience - it is the actual
    behaviour of the system. Below `agents <= traffic` the queue is
    unstable: work arrives at least as fast as it can be cleared, waiting
    time grows without bound, and no service level is achievable at any
    percentile.
    """
    if traffic <= 0:
        return 0.0
    if agents <= traffic:
        return 1.0

    b = erlang_b(traffic, agents)
    rho = traffic / agents
    denominator = 1.0 - rho * (1.0 - b)
    if denominator <= 0:
        return 1.0
    return min(1.0, b / denominator)


def service_level(traffic: float, agents: int, aht_seconds: float, target_seconds: float) -> float:
    """Share of contacts answered within `target_seconds`.

    SL(t) = 1 - C * exp(-(agents - traffic) * t / AHT)
    """
    if traffic <= 0:
        return 1.0
    if agents <= traffic:
        return 0.0
    c = erlang_c(traffic, agents)
    exponent = -(agents - traffic) * target_seconds / aht_seconds
    return float(min(1.0, max(0.0, 1.0 - c * np.exp(exponent))))


def average_speed_of_answer(traffic: float, agents: int, aht_seconds: float) -> float:
    """Mean wait across all contacts, answered or not (seconds)."""
    if traffic <= 0:
        return 0.0
    if agents <= traffic:
        return float("inf")
    return float(erlang_c(traffic, agents) * aht_seconds / (agents - traffic))


def _agents_for_service_level(
    traffic: float, aht_seconds: float, sl_target: float, sl_seconds: float
) -> int:
    """Fewest agents achieving the service level, by binary search.

    Service level is monotonically increasing in agent count, so a binary
    search is exact rather than approximate - it finds the same integer a
    linear scan would, in logarithmic time instead of linear. That matters
    because a full plan sizes tens of thousands of intervals, and each
    Erlang C evaluation is itself O(agents); the linear scan makes plan
    construction quadratic in the size of the operation.
    """
    lower = max(1, int(np.floor(traffic)) + 1)
    if service_level(traffic, lower, aht_seconds, sl_seconds) >= sl_target:
        return lower

    upper = lower
    while upper < MAX_AGENTS:
        upper = min(MAX_AGENTS, max(upper * 2, lower + 1))
        if service_level(traffic, upper, aht_seconds, sl_seconds) >= sl_target:
            break
    else:
        return MAX_AGENTS

    while lower < upper:
        mid = (lower + upper) // 2
        if service_level(traffic, mid, aht_seconds, sl_seconds) >= sl_target:
            upper = mid
        else:
            lower = mid + 1
    return lower


@dataclass
class IntervalRequirement:
    """What one interval needs, and what that delivers."""

    contacts: float
    traffic_erlangs: float
    agents_required: float          # on the phone, before shrinkage
    service_level: float
    asa_seconds: float
    occupancy: float
    binding_constraint: str         # 'service_level' | 'occupancy' | 'none'

    def as_row(self) -> dict:
        return {
            "contacts": round(self.contacts, 1),
            "traffic_erlangs": round(self.traffic_erlangs, 3),
            "agents_required": round(self.agents_required, 2),
            "service_level": round(self.service_level, 4),
            "asa_seconds": round(self.asa_seconds, 1),
            "occupancy": round(self.occupancy, 4),
            "binding_constraint": self.binding_constraint,
        }


def staff_required(
    contacts: float,
    aht_seconds: float,
    interval_seconds: float = 1800.0,
    sl_target: float = 0.80,
    sl_seconds: float = 20.0,
    max_occupancy: float = 0.85,
    concurrency: float = 1.0,
) -> IntervalRequirement:
    """Smallest agent count meeting both the service level and the occupancy cap.

    Two constraints, and the occupancy cap is not a nicety. Erlang C will
    happily report that ninety-four agents hit an 80/20 service level at
    97% occupancy. That figure is arithmetically true and operationally
    fictional: advisors at 97% occupancy have no gap between calls, and
    within a fortnight the real AHT rises, adherence falls and attrition
    climbs - so the plan that assumed it under-delivers on all three. The
    cap makes the trade-off explicit and `binding_constraint` records
    which of the two actually drove the number, so a planner can see at a
    glance whether an interval is service-driven or occupancy-driven.

    `concurrency` divides the workload for channels where one advisor
    handles several contacts at once. It is applied to the traffic before
    the queueing calculation, which treats a chat advisor as `concurrency`
    parallel servers - an approximation, and a slightly optimistic one,
    since a real advisor juggling three chats is not three independent
    servers.
    """
    if contacts <= 0 or aht_seconds <= 0:
        return IntervalRequirement(0.0, 0.0, 0.0, 1.0, 0.0, 0.0, "none")

    traffic = contacts * aht_seconds / interval_seconds / max(concurrency, 1e-9)
    sl_driven = _agents_for_service_level(traffic, aht_seconds, sl_target, sl_seconds)
    # Occupancy = traffic / agents, so the cap sets its own floor on
    # headcount independently of the queueing result.
    occupancy_driven = int(np.ceil(traffic / max_occupancy)) if max_occupancy > 0 else sl_driven
    agents = max(sl_driven, occupancy_driven)

    if occupancy_driven > sl_driven:
        binding = "occupancy"
    elif sl_driven > int(np.ceil(traffic)):
        binding = "service_level"
    else:
        binding = "none"

    return IntervalRequirement(
        contacts=contacts,
        traffic_erlangs=traffic,
        agents_required=float(agents),
        service_level=service_level(traffic, agents, aht_seconds, sl_seconds),
        asa_seconds=average_speed_of_answer(traffic, agents, aht_seconds),
        occupancy=traffic / agents if agents else 0.0,
        binding_constraint=binding,
    )


# ─────────────────────────────────────────────────────────────────────
# Erlang A - queueing with abandonment
# ─────────────────────────────────────────────────────────────────────

@dataclass
class ErlangAResult:
    """Exact stationary metrics for M/M/N+M (Erlang A)."""

    probability_wait: float
    probability_abandon: float
    asa_seconds: float
    occupancy: float


def erlang_a(
    contacts: float,
    aht_seconds: float,
    agents: int,
    patience_seconds: float,
    interval_seconds: float = 1800.0,
    concurrency: float = 1.0,
    max_queue: int = 800,
) -> ErlangAResult:
    """Erlang A metrics from the birth-death chain, computed exactly.

    The M/M/N+M queue is a birth-death process: arrivals at rate lambda in
    every state; departures at `n * mu` while servers are filling, and at
    `N * mu + j * theta` once `j` customers are queued, where `theta` is
    the abandonment rate (one over mean patience). Because it is a
    birth-death chain the stationary distribution has a product form and
    can be built by simple forward recursion - no matrix algebra and no
    approximation.

    The recursion is carried in ratios to state zero and normalised at the
    end, and each ratio is built from the previous one, so nothing here
    overflows the way a factorial form would.

    Note this returns abandonment and waiting probabilities but **not** a
    service level within a target time. The waiting-time distribution
    under abandonment is a phase-type convolution that is expensive to
    evaluate per interval, and approximating it would undercut the point
    of having an exact model. Staffing runs on Erlang C; Erlang A is here
    to price what that assumption costs.
    """
    if contacts <= 0 or agents <= 0:
        return ErlangAResult(0.0, 0.0, 0.0, 0.0)

    effective_agents = max(1, int(agents))
    arrival_rate = contacts / interval_seconds
    service_rate = concurrency / aht_seconds          # per agent
    theta = 1.0 / max(patience_seconds, 1e-9)

    # p[n] relative to p[0], for n = 0 .. N (servers filling).
    ratios = [1.0]
    for n in range(1, effective_agents + 1):
        ratios.append(ratios[-1] * arrival_rate / (n * service_rate))

    # Queue states N+1 .. N+max_queue.
    queue_ratios = []
    current = ratios[-1]
    for j in range(1, max_queue + 1):
        current = current * arrival_rate / (effective_agents * service_rate + j * theta)
        queue_ratios.append(current)
        if current < 1e-14 * ratios[-1] and j > 10:
            break

    total = sum(ratios) + sum(queue_ratios)
    if total <= 0:
        return ErlangAResult(0.0, 0.0, 0.0, 0.0)

    p_wait = (ratios[-1] + sum(queue_ratios)) / total

    # Abandonment: expected abandonment rate over arrival rate.
    abandon_rate = sum(j * q for j, q in enumerate(queue_ratios, start=1)) * theta / total
    p_abandon = min(1.0, abandon_rate / arrival_rate) if arrival_rate > 0 else 0.0

    # Little's law on the queue gives the mean wait across all arrivals.
    mean_queue = sum(j * q for j, q in enumerate(queue_ratios, start=1)) / total
    asa = mean_queue / arrival_rate if arrival_rate > 0 else 0.0

    served_rate = arrival_rate * (1.0 - p_abandon)
    occupancy = served_rate / (effective_agents * service_rate) if effective_agents else 0.0

    return ErlangAResult(
        probability_wait=float(p_wait),
        probability_abandon=float(p_abandon),
        asa_seconds=float(asa),
        occupancy=float(min(occupancy, 1.0)),
    )


def staff_required_erlang_a(
    contacts: float,
    aht_seconds: float,
    patience_seconds: float,
    max_abandon: float = 0.05,
    interval_seconds: float = 1800.0,
    concurrency: float = 1.0,
) -> int:
    """Smallest agent count holding abandonment at or below `max_abandon`."""
    if contacts <= 0:
        return 0
    traffic = contacts * aht_seconds / interval_seconds / max(concurrency, 1e-9)
    agents = max(1, int(np.floor(traffic * 0.5)))
    while agents < MAX_AGENTS:
        result = erlang_a(contacts, aht_seconds, agents, patience_seconds,
                          interval_seconds, concurrency)
        if result.probability_abandon <= max_abandon:
            return agents
        agents += 1
    return agents


# ─────────────────────────────────────────────────────────────────────
# Deferrable workload
# ─────────────────────────────────────────────────────────────────────

def deferrable_fte(
    contacts: float,
    aht_seconds: float,
    available_hours: float,
    productive_utilisation: float = 0.85,
) -> float:
    """Advisors needed to clear a deferrable workload within its window.

    No queueing theory involved, and that is the point. An email answered
    in six hours is as compliant as one answered in six minutes, so there
    is no waiting-time distribution to satisfy - only enough productive
    hours to work the stock down inside the SLA.

    `productive_utilisation` is the share of a rostered hour that turns
    into completed work once reading, system time and task switching are
    taken off. It sits well below 1.0 and above the occupancy an
    interactive channel could sustain, because there is no queue to
    interrupt the advisor.
    """
    if contacts <= 0 or available_hours <= 0:
        return 0.0
    workload_hours = contacts * aht_seconds / 3600.0
    return float(workload_hours / (available_hours * max(productive_utilisation, 1e-9)))
