"""SLO tracking with auto-rollback triggers.

SLOs:
- Workflow success rate: ≥99.5%, auto-rollback if <99.0% for 15min
- Hallucination ceiling: ≤0.5%, alert + HITL review
- Incorrect tool execution: ≤0.1%, circuit breaker + rollback
- Cost variance: ≤15%, FinOps alert
- Provenance completeness: 100%, block deployment if <100%

Playbook v8.0 Part 17.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

logger = logging.getLogger(__name__)


class SLOStatus(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    BREACHED = "breached"
    ROLLBACK = "rollback"


class SLOAction(str, Enum):
    NONE = "none"
    ALERT = "alert"
    HITL_REVIEW = "hitl_review"
    CIRCUIT_BREAK = "circuit_break"
    AUTO_ROLLBACK = "auto_rollback"
    BLOCK_DEPLOYMENT = "block_deployment"


@dataclass
class SLODefinition:
    """Definition of a single SLO."""

    name: str
    target: float
    breach_threshold: float
    direction: str  # "above" (value must be >= target) or "below" (value must be <= target)
    breach_action: SLOAction
    sustained_window_seconds: int = 900  # 15 min default

    def evaluate(self, value: float) -> SLOStatus:
        if self.direction == "above":
            if value >= self.target:
                return SLOStatus.HEALTHY
            elif value >= self.breach_threshold:
                return SLOStatus.DEGRADED
            return SLOStatus.BREACHED
        else:  # below
            if value <= self.target:
                return SLOStatus.HEALTHY
            elif value <= self.breach_threshold:
                return SLOStatus.DEGRADED
            return SLOStatus.BREACHED


@dataclass
class SLOMeasurement:
    """A single SLO measurement."""

    slo_name: str
    value: float
    status: SLOStatus
    timestamp: float


@dataclass
class SLOBreach:
    """Record of an SLO breach event."""

    slo_name: str
    value: float
    threshold: float
    action_taken: SLOAction
    timestamp: float
    sustained: bool = False


class SLOTracker:
    """Tracks SLOs across the system and triggers remediation."""

    DEFAULT_SLOS = [
        SLODefinition("workflow_success_rate", 0.995, 0.990, "above", SLOAction.AUTO_ROLLBACK),
        SLODefinition("hallucination_rate", 0.005, 0.010, "below", SLOAction.HITL_REVIEW),
        SLODefinition("incorrect_tool_execution", 0.001, 0.005, "below", SLOAction.CIRCUIT_BREAK),
        SLODefinition("cost_variance", 0.15, 0.25, "below", SLOAction.ALERT),
        SLODefinition("provenance_completeness", 1.0, 0.99, "above", SLOAction.BLOCK_DEPLOYMENT),
    ]

    def __init__(self, slos: list[SLODefinition] | None = None) -> None:
        self._slos = {s.name: s for s in (slos or self.DEFAULT_SLOS)}
        self._history: dict[str, list[SLOMeasurement]] = {}
        self._breaches: list[SLOBreach] = []
        self._action_handlers: dict[SLOAction, Callable[..., None]] = {}

    def register_action_handler(self, action: SLOAction, handler: Callable[..., None]) -> None:
        """Register a handler for an SLO breach action."""
        self._action_handlers[action] = handler

    def record(self, slo_name: str, value: float) -> SLOBreach | None:
        """Record a measurement and check for breaches."""
        slo = self._slos.get(slo_name)
        if slo is None:
            logger.warning("Unknown SLO: %s", slo_name)
            return None

        status = slo.evaluate(value)
        measurement = SLOMeasurement(
            slo_name=slo_name,
            value=value,
            status=status,
            timestamp=time.time(),
        )
        self._history.setdefault(slo_name, []).append(measurement)

        # Keep bounded history
        if len(self._history[slo_name]) > 1000:
            self._history[slo_name] = self._history[slo_name][-1000:]

        if status == SLOStatus.BREACHED:
            sustained = self._is_sustained(slo_name, slo.sustained_window_seconds)
            breach = SLOBreach(
                slo_name=slo_name,
                value=value,
                threshold=slo.breach_threshold,
                action_taken=slo.breach_action,
                timestamp=time.time(),
                sustained=sustained,
            )
            self._breaches.append(breach)

            if sustained:
                logger.error(
                    "SUSTAINED SLO BREACH: %s=%.4f (threshold=%.4f) → %s",
                    slo_name, value, slo.breach_threshold, slo.breach_action.value,
                )
                handler = self._action_handlers.get(slo.breach_action)
                if handler:
                    handler(breach)
            else:
                logger.warning("SLO breach: %s=%.4f", slo_name, value)

            return breach
        return None

    def dashboard(self) -> dict[str, Any]:
        """Return current SLO status for all tracked metrics."""
        result = {}
        for name, slo in self._slos.items():
            history = self._history.get(name, [])
            if history:
                latest = history[-1]
                result[name] = {
                    "target": slo.target,
                    "latest_value": round(latest.value, 6),
                    "status": latest.status.value,
                    "breach_action": slo.breach_action.value,
                    "measurements": len(history),
                }
            else:
                result[name] = {
                    "target": slo.target,
                    "latest_value": None,
                    "status": "no_data",
                }

        return {
            "slos": result,
            "total_breaches": len(self._breaches),
            "recent_breaches": len([b for b in self._breaches if time.time() - b.timestamp < 3600]),
        }

    def _is_sustained(self, slo_name: str, window_seconds: int) -> bool:
        """Check if breach has been sustained for the full window."""
        history = self._history.get(slo_name, [])
        if not history:
            return False

        now = time.time()
        cutoff = now - window_seconds
        recent = [m for m in history if m.timestamp >= cutoff]

        if len(recent) < 3:  # Need at least 3 measurements to call it sustained
            return False

        return all(m.status == SLOStatus.BREACHED for m in recent)
