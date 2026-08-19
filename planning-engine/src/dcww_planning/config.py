"""Planning configuration for the Retail contact operation.

This module is deliberately declarative. Every number a planner would
argue about in a review meeting - target service level, assumed AHT,
shrinkage components, chat concurrency, the cost of an hour of overtime -
lives here as a named field rather than buried in the calculation. That
separation is the difference between a model you can defend in a
stakeholder session and a spreadsheet nobody trusts.

All figures are illustrative and synthetic. They are shaped to be
structurally realistic for a UK water retailer - a billing-led demand
mix, a 24/7 operational emergency line, a small Welsh-language skill
pool - but they are not Welsh Water's actual operating data.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

__all__ = [
    "ChannelSpec", "ServiceLine", "OpeningHours", "Shrinkage", "CostModel",
    "SupplyAssumptions", "PlanConfig", "default_config",
    "CHANNELS", "SERVICE_LINES", "INTERVALS_PER_DAY", "INTERVAL_MINUTES",
]

INTERVAL_MINUTES = 30
INTERVALS_PER_DAY = (24 * 60) // INTERVAL_MINUTES  # 48


# ─────────────────────────────────────────────────────────────────────
# Channels
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ChannelSpec:
    """How one contact channel behaves for capacity purposes.

    The `kind` field is the important one. It decides which piece of
    mathematics applies, and getting it wrong is the classic multi-channel
    planning error:

    - `interactive` contacts arrive randomly and must be answered while
      the customer waits, so queueing theory (Erlang) governs. You cannot
      run these at 100% occupancy: the queue explodes.
    - `deferrable` contacts can be banked and worked down against an SLA
      measured in hours or days, so a workload/productivity calculation
      governs. Applying Erlang here over-staffs badly.
    """

    key: str
    label: str
    kind: str                       # 'interactive' | 'deferrable'
    aht_seconds: float              # average handle time (talk + wrap)
    concurrency: float = 1.0        # simultaneous contacts per advisor
    service_level_target: float = 0.80
    service_level_seconds: float = 20.0
    sla_hours: float = 24.0         # deferrable channels only
    max_occupancy: float = 0.85     # interactive channels only
    patience_seconds: float = 90.0  # mean time before a caller abandons
    productive_utilisation: float = 0.85  # deferrable throughput allowance


CHANNELS: tuple[ChannelSpec, ...] = (
    ChannelSpec(
        key="voice", label="Voice", kind="interactive",
        aht_seconds=402, concurrency=1.0,
        service_level_target=0.80, service_level_seconds=20.0,
        max_occupancy=0.85, patience_seconds=95.0,
    ),
    ChannelSpec(
        # Chat advisors hold more than one conversation at a time, but the
        # gain is sub-linear: concurrency 2.5 does not mean 2.5x the
        # throughput, because each extra thread lengthens handle time.
        # 2.2 effective against a nominal 2.5 is the honest assumption.
        key="webchat", label="Web chat", kind="interactive",
        aht_seconds=612, concurrency=2.2,
        service_level_target=0.80, service_level_seconds=30.0,
        max_occupancy=0.82, patience_seconds=60.0,
    ),
    ChannelSpec(
        key="email", label="Email", kind="deferrable",
        aht_seconds=480, sla_hours=24.0, productive_utilisation=0.85,
    ),
    ChannelSpec(
        key="messaging", label="Social / WhatsApp", kind="deferrable",
        aht_seconds=300, sla_hours=4.0, productive_utilisation=0.80,
    ),
    ChannelSpec(
        key="back_office", label="Back office", kind="deferrable",
        aht_seconds=690, sla_hours=72.0, productive_utilisation=0.88,
    ),
)

CHANNEL_BY_KEY = {c.key: c for c in CHANNELS}


# ─────────────────────────────────────────────────────────────────────
# Opening hours
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class OpeningHours:
    """Opening hours as (open, close) decimal hours per weekday, Mon=0.

    `None` means closed. A 24/7 line is (0.0, 24.0) every day - which is
    genuinely the case for a water company's leak and supply-interruption
    lines, and is what makes this a night-shift planning problem rather
    than a nine-to-five one.
    """

    by_weekday: tuple[tuple[float, float] | None, ...]

    def is_open(self, weekday: int, hour: float) -> bool:
        window = self.by_weekday[weekday]
        if window is None:
            return False
        start, end = window
        return start <= hour < end

    def open_hours(self, weekday: int) -> float:
        window = self.by_weekday[weekday]
        return 0.0 if window is None else window[1] - window[0]


OFFICE_HOURS = OpeningHours((
    (8.0, 18.0),   # Mon
    (8.0, 18.0),
    (8.0, 18.0),
    (8.0, 18.0),
    (8.0, 18.0),   # Fri
    (8.5, 13.5),   # Sat
    None,          # Sun
))

ALWAYS_ON = OpeningHours(tuple([(0.0, 24.0)] * 7))

BACK_OFFICE_HOURS = OpeningHours((
    (8.0, 18.0), (8.0, 18.0), (8.0, 18.0), (8.0, 18.0), (8.0, 18.0), None, None,
))


# ─────────────────────────────────────────────────────────────────────
# Service lines (queue x channel)
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ServiceLine:
    """One planning entity: a queue on a channel.

    This is the level a plan is actually built at. Rolling up to "total
    contacts" hides the fact that a 24/7 emergency queue and a weekday
    billing queue need completely different shift patterns, and rolling
    down to individual skills produces volumes too small to forecast.

    `event_sensitivity` maps an event name from the calendar module to the
    proportional volume uplift that event causes on this line. This is the
    domain knowledge that separates a water-company forecast from a
    generic one: a charges notification triples billing calls and does
    nothing at all to leak reporting.
    """

    key: str
    queue: str
    channel: str
    label: str
    base_daily_volume: float
    hours: OpeningHours
    aht_multiplier: float = 1.0
    welsh_language: bool = False
    weekly_shape: tuple[float, ...] = (1.18, 1.06, 1.00, 0.98, 1.02, 0.52, 0.24)
    annual_amplitude: float = 0.10          # +/- share from annual seasonality
    annual_peak_week: int = 6               # ISO week of the seasonal peak
    trend_per_year: float = 0.0             # proportional growth per year
    event_sensitivity: dict[str, float] = field(default_factory=dict)


def _service_lines() -> tuple[ServiceLine, ...]:
    """The pan-Retail service line set.

    Volumes are illustrative and sized for a retailer serving roughly
    three million customers: billing dominates, operational lines are
    smaller but must be answered around the clock, and digital channels
    are growing while voice slowly declines.
    """
    billing_events = {
        "annual_charges_notification": 1.15,
        "april_tariff_change": 1.10,
        "annual_bill_issue": 1.00,
        "direct_debit_collection": 0.38,
        "helpu_campaign": 0.22,
    }
    metering_events = {
        "meter_read_cycle": 0.85,
        "annual_bill_issue": 0.40,
        "dry_weather_spell": 0.18,
    }
    operational_events = {
        "freeze_thaw": 3.20,
        "storm_event": 1.60,
        "dry_weather_spell": 0.45,
    }
    affordability_events = {
        "helpu_campaign": 1.60,
        "psr_campaign": 0.70,
        "annual_charges_notification": 0.70,
        "direct_debit_collection": 0.30,
    }

    return (
        # ── Billing & payments: the volume engine of the operation ──
        ServiceLine(
            key="billing.voice", queue="Billing & payments", channel="voice",
            label="Billing & payments - Voice", base_daily_volume=2450,
            hours=OFFICE_HOURS, annual_amplitude=0.16, annual_peak_week=8,
            trend_per_year=-0.06, event_sensitivity=billing_events,
        ),
        ServiceLine(
            key="billing.webchat", queue="Billing & payments", channel="webchat",
            label="Billing & payments - Web chat", base_daily_volume=880,
            hours=OFFICE_HOURS, annual_amplitude=0.14, annual_peak_week=8,
            trend_per_year=0.18, event_sensitivity=billing_events,
        ),
        ServiceLine(
            key="billing.email", queue="Billing & payments", channel="email",
            label="Billing & payments - Email", base_daily_volume=640,
            hours=BACK_OFFICE_HOURS, annual_amplitude=0.13, annual_peak_week=8,
            trend_per_year=0.05, event_sensitivity=billing_events,
        ),
        ServiceLine(
            key="billing.messaging", queue="Billing & payments", channel="messaging",
            label="Billing & payments - Social / WhatsApp", base_daily_volume=210,
            hours=OFFICE_HOURS, annual_amplitude=0.12, annual_peak_week=8,
            trend_per_year=0.34, event_sensitivity=billing_events,
        ),

        # ── Metering ──
        ServiceLine(
            key="metering.voice", queue="Metering", channel="voice",
            label="Metering - Voice", base_daily_volume=470,
            hours=OFFICE_HOURS, annual_amplitude=0.11, annual_peak_week=28,
            trend_per_year=0.04, event_sensitivity=metering_events,
        ),
        ServiceLine(
            key="metering.email", queue="Metering", channel="email",
            label="Metering - Email", base_daily_volume=180,
            hours=BACK_OFFICE_HOURS, annual_amplitude=0.10, annual_peak_week=28,
            trend_per_year=0.07, event_sensitivity=metering_events,
        ),

        # ── Operational: 24/7, weather-driven, non-negotiable ──
        ServiceLine(
            key="operations.voice", queue="Leaks & supply interruption", channel="voice",
            label="Leaks & supply interruption - Voice", base_daily_volume=760,
            hours=ALWAYS_ON, aht_multiplier=0.82,
            weekly_shape=(1.08, 1.02, 1.00, 1.00, 1.04, 0.92, 0.86),
            annual_amplitude=0.22, annual_peak_week=3,
            trend_per_year=0.01, event_sensitivity=operational_events,
        ),
        ServiceLine(
            key="operations.messaging", queue="Leaks & supply interruption", channel="messaging",
            label="Leaks & supply interruption - Social / WhatsApp", base_daily_volume=145,
            hours=ALWAYS_ON, annual_amplitude=0.24, annual_peak_week=3,
            weekly_shape=(1.08, 1.02, 1.00, 1.00, 1.04, 0.92, 0.86),
            trend_per_year=0.29, event_sensitivity=operational_events,
        ),

        # ── Water quality ──
        ServiceLine(
            key="quality.voice", queue="Water quality", channel="voice",
            label="Water quality - Voice", base_daily_volume=195,
            hours=ALWAYS_ON, aht_multiplier=1.12,
            weekly_shape=(1.10, 1.04, 1.00, 0.99, 1.02, 0.78, 0.62),
            annual_amplitude=0.18, annual_peak_week=30,
            event_sensitivity={"dry_weather_spell": 0.55, "storm_event": 0.85, "freeze_thaw": 0.60},
        ),

        # ── Affordability & debt: HelpU, WaterSure Wales, payment plans ──
        ServiceLine(
            key="affordability.voice", queue="Affordability & debt", channel="voice",
            label="Affordability & debt - Voice", base_daily_volume=520,
            hours=OFFICE_HOURS, aht_multiplier=1.34,
            annual_amplitude=0.15, annual_peak_week=4,
            trend_per_year=0.09, event_sensitivity=affordability_events,
        ),
        ServiceLine(
            key="affordability.back_office", queue="Affordability & debt", channel="back_office",
            label="Affordability & debt - Back office", base_daily_volume=310,
            hours=BACK_OFFICE_HOURS, annual_amplitude=0.14, annual_peak_week=4,
            trend_per_year=0.09, event_sensitivity=affordability_events,
        ),

        # ── Move home ──
        ServiceLine(
            key="movehome.voice", queue="Move home", channel="voice",
            label="Move home - Voice", base_daily_volume=340,
            hours=OFFICE_HOURS, annual_amplitude=0.20, annual_peak_week=31,
            trend_per_year=-0.03, event_sensitivity={"annual_bill_issue": 0.15},
        ),
        ServiceLine(
            key="movehome.webchat", queue="Move home", channel="webchat",
            label="Move home - Web chat", base_daily_volume=190,
            hours=OFFICE_HOURS, annual_amplitude=0.20, annual_peak_week=31,
            trend_per_year=0.21, event_sensitivity={"annual_bill_issue": 0.15},
        ),

        # ── Welsh language line ──
        # Small, skill-restricted and expected as a matter of course by
        # Welsh-speaking customers. It is carried as its own service line
        # precisely because it cannot be pooled: a 60-call-a-day queue
        # needs proportionally far more headcount than a 2,000-call one to
        # hit the same service level, and any plan that buries it inside
        # the voice total will quietly under-staff it.
        ServiceLine(
            key="welsh.voice", queue="Welsh language (Cymraeg)", channel="voice",
            label="Welsh language line - Voice", base_daily_volume=58,
            hours=OFFICE_HOURS, aht_multiplier=1.08, welsh_language=True,
            annual_amplitude=0.14, annual_peak_week=8,
            trend_per_year=0.03,
            event_sensitivity={"annual_charges_notification": 1.05,
                               "annual_bill_issue": 0.85,
                               "st_davids_day": 0.35},
        ),

        # ── Complaints & back office ──
        ServiceLine(
            key="complaints.back_office", queue="Complaints", channel="back_office",
            label="Complaints - Back office", base_daily_volume=165,
            hours=BACK_OFFICE_HOURS, aht_multiplier=1.55,
            annual_amplitude=0.16, annual_peak_week=9,
            trend_per_year=0.02,
            event_sensitivity={"annual_charges_notification": 0.55,
                               "april_tariff_change": 0.75,
                               "storm_event": 0.60},
        ),
        ServiceLine(
            key="billing.back_office", queue="Billing & payments", channel="back_office",
            label="Billing & payments - Back office", base_daily_volume=520,
            hours=BACK_OFFICE_HOURS, annual_amplitude=0.13, annual_peak_week=8,
            event_sensitivity=billing_events,
        ),
    )


SERVICE_LINES: tuple[ServiceLine, ...] = _service_lines()
LINE_BY_KEY = {s.key: s for s in SERVICE_LINES}


# ─────────────────────────────────────────────────────────────────────
# Shrinkage
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Shrinkage:
    """Component shrinkage, built up rather than assumed as one number.

    Two properties matter and are routinely conflated:

    - **Regular shrinkage** is planned and rostered - annual leave,
      training, team meetings, coaching, paid breaks. It is known in
      advance and belongs in the capacity plan.
    - **Irregular shrinkage** is unplanned - sickness, absence, system
      outages, unscheduled off-phone time. It is a risk allowance.

    They are combined *multiplicatively*, not additively. Adding them is
    the most common shrinkage error in the industry and it systematically
    under-staffs: 20% regular and 7% irregular is not 27% shrinkage, it is
    1 - (0.80 x 0.93). Over a few hundred seats the gap between the two
    conventions is worth several FTE.
    """

    annual_leave: float = 0.114     # ~26 days + bank holidays over 260
    sickness: float = 0.045
    training: float = 0.035
    coaching_1to1: float = 0.020
    team_meetings: float = 0.012
    paid_breaks: float = 0.062
    system_downtime: float = 0.008
    other_offline: float = 0.018

    @property
    def regular(self) -> float:
        """Planned, rostered off-phone time."""
        return 1.0 - (
            (1 - self.annual_leave)
            * (1 - self.training)
            * (1 - self.coaching_1to1)
            * (1 - self.team_meetings)
            * (1 - self.paid_breaks)
        )

    @property
    def irregular(self) -> float:
        """Unplanned off-phone time."""
        return 1.0 - ((1 - self.sickness) * (1 - self.system_downtime) * (1 - self.other_offline))

    @property
    def total(self) -> float:
        """Combined shrinkage, compounded rather than summed."""
        return 1.0 - (1 - self.regular) * (1 - self.irregular)

    @property
    def uplift_factor(self) -> float:
        """Multiplier from 'required on the phone' to 'required rostered'."""
        return 1.0 / (1.0 - self.total)

    def components(self) -> dict[str, float]:
        return {
            "Annual leave": self.annual_leave,
            "Sickness": self.sickness,
            "Training": self.training,
            "Coaching / 1-2-1": self.coaching_1to1,
            "Team meetings": self.team_meetings,
            "Paid breaks": self.paid_breaks,
            "System downtime": self.system_downtime,
            "Other offline": self.other_offline,
        }


# ─────────────────────────────────────────────────────────────────────
# Cost and supply
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CostModel:
    """Cost of serving. The JD asks for KPIs met 'in the most
    cost-effective manner', which means the plan has to price its own
    options, not just count heads."""

    advisor_hourly_cost: float = 17.80      # fully loaded
    overtime_multiplier: float = 1.35
    agency_multiplier: float = 1.52
    recruitment_cost_per_head: float = 2400.0
    contracted_hours_per_week: float = 37.0
    weeks_per_year: float = 52.0

    @property
    def annual_fte_cost(self) -> float:
        return self.advisor_hourly_cost * self.contracted_hours_per_week * self.weeks_per_year


@dataclass(frozen=True)
class SupplyAssumptions:
    """How many advisors actually turn up, week by week.

    Supply is not a constant. Attrition erodes it continuously, and
    recruitment does not replace it instantly: there is a lead time from
    offer to a fully productive advisor, and new starters are not
    productive during it. Ignoring the training pipeline is how plans that
    look fine in a spreadsheet fail in March.
    """

    opening_fte: float = 331.0
    annual_attrition: float = 0.235
    training_weeks: int = 6
    nesting_weeks: int = 3
    nesting_productivity: float = 0.55      # productivity during nesting
    recruitment_lead_weeks: int = 5         # offer to classroom
    max_intake_per_month: int = 30

    @property
    def weekly_attrition(self) -> float:
        """Weekly leaver rate consistent with the annual figure.

        Compounded, not divided by 52: attrition applies to a shrinking
        base, so 23.5% a year is not 0.452% a week.
        """
        return 1.0 - (1.0 - self.annual_attrition) ** (1.0 / 52.0)


# ─────────────────────────────────────────────────────────────────────
# Top-level configuration
# ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class PlanConfig:
    """Everything the engine needs to produce a plan."""

    name: str = "Dwr Cymru Welsh Water - Retail Planning & Performance"
    channels: tuple[ChannelSpec, ...] = CHANNELS
    service_lines: tuple[ServiceLine, ...] = SERVICE_LINES
    shrinkage: Shrinkage = Shrinkage()
    cost: CostModel = CostModel()
    supply: SupplyAssumptions = SupplyAssumptions()

    # Planning horizons, in the language the JD uses.
    short_term_days: int = 28        # in-day to four weeks: rosters, RTA
    medium_term_weeks: int = 26      # recruitment, leave, overtime budget
    long_term_months: int = 24       # headcount envelope and annual budget

    seed: int = 20260824             # interview date, for reproducibility

    def channel(self, key: str) -> ChannelSpec:
        return CHANNEL_BY_KEY[key]

    def line(self, key: str) -> ServiceLine:
        return LINE_BY_KEY[key]

    def with_shrinkage(self, **kwargs) -> "PlanConfig":
        return replace(self, shrinkage=replace(self.shrinkage, **kwargs))


def default_config() -> PlanConfig:
    return PlanConfig()
