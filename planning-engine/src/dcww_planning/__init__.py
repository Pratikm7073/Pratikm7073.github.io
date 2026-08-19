"""Retail contact centre resource planning and forecasting engine.

A working demand-forecasting and capacity-planning engine for a
multi-channel water retailer's contact operation: forecast contacts by
queue and channel, size the requirement with queueing theory, model the
supply of advisors against attrition and the recruitment pipeline, and
report the gap, its cost and what to do about it.

All data is synthetic. See README.md.
"""

__version__ = "1.0.0"

from .config import PlanConfig, default_config

__all__ = ["PlanConfig", "default_config", "__version__"]
