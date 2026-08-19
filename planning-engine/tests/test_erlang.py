"""Queueing mathematics, checked against published values and identities.

The reference figures are from standard Erlang B/C tables, not from this
implementation. A test that only checks the code against itself would pass
just as happily on a formula with a transposed term.
"""

import numpy as np
import pytest

from dcww_planning.erlang import (
    _agents_for_service_level, average_speed_of_answer, deferrable_fte, erlang_a,
    erlang_b, erlang_c, service_level, staff_required, staff_required_erlang_a,
)


# ── Erlang B ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("traffic,agents,expected", [
    (1.0, 1, 0.5),            # A/(1+A)
    (2.0, 2, 0.4),            # published table value
    (1.0, 2, 1.0 / 5.0),
    (10.0, 10, 0.2146),       # standard Erlang B table
    (5.0, 8, 0.0700),
])
def test_erlang_b_matches_published_values(traffic, agents, expected):
    assert erlang_b(traffic, agents) == pytest.approx(expected, abs=1e-4)


def test_erlang_b_is_decreasing_in_agents():
    values = [erlang_b(10.0, n) for n in range(1, 40)]
    assert all(a > b for a, b in zip(values, values[1:]))


def test_erlang_b_survives_large_inputs():
    """The factorial form overflows here; the recursion must not."""
    value = erlang_b(500.0, 600)
    assert 0.0 < value < 1.0
    assert np.isfinite(value)


# ── Erlang C ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("traffic,agents,expected", [
    (10.0, 11, 0.6821),
    (10.0, 12, 0.4494),
    (10.0, 13, 0.2853),
    (10.0, 15, 0.1020),
])
def test_erlang_c_matches_published_values(traffic, agents, expected):
    assert erlang_c(traffic, agents) == pytest.approx(expected, abs=1e-4)


def test_erlang_c_saturates_when_agents_do_not_exceed_load():
    """Below stability every arrival waits, and the queue never clears."""
    assert erlang_c(10.0, 10) == 1.0
    assert erlang_c(10.0, 9) == 1.0
    assert service_level(10.0, 10, 180.0, 20.0) == 0.0
    assert average_speed_of_answer(10.0, 10, 180.0) == float("inf")


def test_service_level_is_monotonic_in_agents():
    levels = [service_level(44.67, n, 402.0, 20.0) for n in range(45, 80)]
    assert all(a <= b for a, b in zip(levels, levels[1:]))
    assert levels[-1] > 0.99


def test_zero_demand_needs_nobody():
    req = staff_required(0, 402, 1800, 0.80, 20, 0.85)
    assert req.agents_required == 0
    assert req.binding_constraint == "none"


# ── The staffing search ────────────────────────────────────────────────

@pytest.mark.parametrize("traffic", [0.5, 3.0, 7.3, 44.67, 111.7])
@pytest.mark.parametrize("target,seconds", [(0.80, 20.0), (0.90, 15.0)])
def test_binary_search_equals_exhaustive_scan(traffic, target, seconds):
    """The fast path must return exactly what the slow path would.

    Binary search is only valid because service level is monotonic in
    agent count. If that ever stopped holding, this test is what would
    catch it.
    """
    scanned = None
    agents = max(1, int(traffic) + 1)
    while agents < 3000:
        if service_level(traffic, agents, 402.0, seconds) >= target:
            scanned = agents
            break
        agents += 1
    assert _agents_for_service_level(traffic, 402.0, target, seconds) == scanned


def test_occupancy_cap_can_bind_instead_of_service_level():
    """On a large queue the occupancy cap sets the floor, not Erlang.

    Big queues pool so well that the service level is satisfied at an
    occupancy no advisor could sustain. The cap is what stops the plan
    banking a number the operation cannot deliver.
    """
    loose = staff_required(500, 402, 1800, 0.80, 20, max_occupancy=0.99)
    capped = staff_required(500, 402, 1800, 0.80, 20, max_occupancy=0.85)
    assert capped.agents_required > loose.agents_required
    assert capped.binding_constraint == "occupancy"
    assert capped.occupancy <= 0.85 + 1e-9


def test_small_queues_have_worse_economies_of_scale():
    """The Welsh-language line argument, as a test.

    Sixty contacts a day cannot pool their variance the way two thousand
    can, so a small queue needs more agents *per contact* to hit the same
    service level. Any plan that buries a small skill inside a large
    queue's total will under-staff it.
    """
    small = staff_required(20, 402, 1800, 0.80, 20, 0.85)
    large = staff_required(400, 402, 1800, 0.80, 20, 0.85)
    small_per_contact = small.agents_required / 20
    large_per_contact = large.agents_required / 400
    assert small_per_contact > large_per_contact * 1.15


def test_concurrency_reduces_the_requirement():
    single = staff_required(200, 600, 1800, 0.80, 30, 0.82, concurrency=1.0)
    concurrent = staff_required(200, 600, 1800, 0.80, 30, 0.82, concurrency=2.2)
    assert concurrent.agents_required < single.agents_required


# ── Erlang A ───────────────────────────────────────────────────────────

def test_erlang_a_converges_to_erlang_c_as_patience_grows():
    """Infinite patience is exactly the Erlang C assumption.

    This is the strongest available check on the birth-death recursion:
    the two models are derived completely differently and must agree in
    the limit.
    """
    contacts, aht, agents = 200, 402.0, 50
    traffic = contacts * aht / 1800.0
    patient = erlang_a(contacts, aht, agents, patience_seconds=10_000_000, interval_seconds=1800)
    assert patient.probability_wait == pytest.approx(erlang_c(traffic, agents), abs=2e-3)
    assert patient.asa_seconds == pytest.approx(
        average_speed_of_answer(traffic, agents, aht), rel=2e-2)
    assert patient.probability_abandon == pytest.approx(0.0, abs=1e-3)


def test_abandonment_falls_as_patience_rises():
    values = [
        erlang_a(200, 402.0, 50, patience_seconds=p, interval_seconds=1800).probability_abandon
        for p in (10, 30, 60, 120, 600)
    ]
    assert all(a > b for a, b in zip(values, values[1:]))


def test_erlang_c_overstaffs_relative_to_an_abandonment_target():
    """Ignoring abandonment costs headcount, and the gap widens with size.

    Erlang C must serve every arrival because nobody ever hangs up, so it
    sizes for a queue that in reality partly clears itself.
    """
    for volume in (250, 500, 900):
        erlang_c_agents = staff_required(volume, 402, 1800, 0.80, 20, 0.85).agents_required
        erlang_a_agents = staff_required_erlang_a(volume, 402, 95.0, max_abandon=0.05)
        assert erlang_a_agents < erlang_c_agents


# ── Deferrable work ────────────────────────────────────────────────────

def test_deferrable_fte_is_workload_over_productive_hours():
    # 100 emails x 480s = 13.333 hours of work; 8 hours available at 85%.
    assert deferrable_fte(100, 480, 8.0, 0.85) == pytest.approx(
        (100 * 480 / 3600) / (8.0 * 0.85))


def test_deferrable_is_much_cheaper_than_treating_email_as_a_queue():
    """Running Erlang on a deferrable channel is the expensive mistake.

    An email with a 24-hour SLA has no waiting-time distribution to
    satisfy, so sizing it for instant answer buys capacity nobody needed.
    """
    volume, aht = 600, 480
    as_deferrable = deferrable_fte(volume, aht, available_hours=10.0, productive_utilisation=0.85)
    as_queue = max(
        staff_required(volume / 20, aht, 1800, 0.80, 20, 0.85).agents_required
        for _ in range(1)
    )
    assert as_deferrable < as_queue


def test_no_work_needs_no_people():
    assert deferrable_fte(0, 480, 8.0) == 0.0
    assert deferrable_fte(100, 480, 0.0) == 0.0
