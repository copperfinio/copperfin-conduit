"""Dashboard package: in-process telemetry and live operator UI."""

from .blueprint import dashboard_blueprint
from .telemetry import telemetry

__all__ = ["dashboard_blueprint", "telemetry"]
