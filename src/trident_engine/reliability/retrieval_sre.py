"""Retrieval SRE — RAG as production infrastructure.

Monitors retrieval quality metrics and triggers auto-remediation
when thresholds are breached.

Metrics:
- Precision@5: >0.78 target, alert <0.70, remediate: retrain reranker
- Grounding accuracy: >0.92 target, alert <0.85, remediate: force re-indexing
- Embedding drift: <0.15 cosine, alert >0.15, remediate: recalibrate
- Hallucination attribution: >80% traceable, alert <60%

Playbook v8.0 Part 9.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class AlertSeverity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class RemediationAction(str, Enum):
    RETRAIN_RERANKER = "retrain_reranker"
    FORCE_REINDEX = "force_reindex"
    RECALIBRATE_EMBEDDINGS = "recalibrate_embeddings"
    IMPROVE_CITATION_LINKAGE = "improve_citation_linkage"
    CIRCUIT_BREAK = "circuit_break"


@dataclass
class RetrievalMetric:
    """A single retrieval quality measurement."""

    name: str
    value: float
    target: float
    alert_threshold: float
    timestamp: float = 0.0

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()

    @property
    def is_healthy(self) -> bool:
        if self.name == "embedding_drift":
            return self.value < self.target
        return self.value >= self.target

    @property
    def is_alerting(self) -> bool:
        if self.name == "embedding_drift":
            return self.value > self.alert_threshold
        return self.value < self.alert_threshold


@dataclass
class RetrievalAlert:
    """Alert triggered by a metric breach."""

    metric_name: str
    severity: AlertSeverity
    current_value: float
    threshold: float
    remediation: RemediationAction
    timestamp: float
    message: str


class RetrievalSRE:
    """SRE monitor for RAG retrieval quality."""

    # Metric definitions: (name, target, alert_threshold, remediation)
    METRIC_DEFS: list[tuple[str, float, float, RemediationAction]] = [
        ("precision_at_5", 0.78, 0.70, RemediationAction.RETRAIN_RERANKER),
        ("grounding_accuracy", 0.92, 0.85, RemediationAction.FORCE_REINDEX),
        ("embedding_drift", 0.15, 0.15, RemediationAction.RECALIBRATE_EMBEDDINGS),
        ("hallucination_attribution", 0.80, 0.60, RemediationAction.IMPROVE_CITATION_LINKAGE),
    ]

    def __init__(self, window_size: int = 100) -> None:
        self.window_size = window_size
        self._history: dict[str, list[RetrievalMetric]] = {}
        self._alerts: list[RetrievalAlert] = []
        self._circuit_broken: bool = False

    def record(self, metric_name: str, value: float) -> RetrievalAlert | None:
        """Record a metric value. Returns an alert if threshold breached."""
        defn = next((d for d in self.METRIC_DEFS if d[0] == metric_name), None)
        if defn is None:
            logger.warning("Unknown retrieval metric: %s", metric_name)
            return None

        name, target, alert_thresh, remediation = defn
        metric = RetrievalMetric(name=name, value=value, target=target, alert_threshold=alert_thresh)

        self._history.setdefault(name, []).append(metric)
        # Keep sliding window
        if len(self._history[name]) > self.window_size:
            self._history[name] = self._history[name][-self.window_size:]

        if metric.is_alerting:
            severity = AlertSeverity.CRITICAL if self._sustained_breach(name) else AlertSeverity.WARNING
            alert = RetrievalAlert(
                metric_name=name,
                severity=severity,
                current_value=value,
                threshold=alert_thresh,
                remediation=remediation,
                timestamp=time.time(),
                message=f"{name}={value:.4f} breached threshold {alert_thresh}",
            )
            self._alerts.append(alert)
            logger.warning("Retrieval alert: %s", alert.message)

            if severity == AlertSeverity.CRITICAL:
                logger.error("CRITICAL: Sustained breach on %s — remediation: %s", name, remediation.value)

            return alert
        return None

    def health_check(self) -> dict[str, Any]:
        """Return current health status across all metrics."""
        status = {}
        for name, target, alert_thresh, _ in self.METRIC_DEFS:
            history = self._history.get(name, [])
            if history:
                latest = history[-1]
                avg = sum(m.value for m in history[-10:]) / min(10, len(history))
                status[name] = {
                    "latest": round(latest.value, 4),
                    "avg_last_10": round(avg, 4),
                    "target": target,
                    "healthy": latest.is_healthy,
                    "alerting": latest.is_alerting,
                }
            else:
                status[name] = {"latest": None, "healthy": True, "alerting": False}

        return {
            "metrics": status,
            "circuit_broken": self._circuit_broken,
            "active_alerts": len([a for a in self._alerts[-10:] if a.severity == AlertSeverity.CRITICAL]),
        }

    def _sustained_breach(self, metric_name: str, lookback: int = 5) -> bool:
        """Check if a metric has been breaching for multiple consecutive readings."""
        history = self._history.get(metric_name, [])
        if len(history) < lookback:
            return False
        return all(m.is_alerting for m in history[-lookback:])
