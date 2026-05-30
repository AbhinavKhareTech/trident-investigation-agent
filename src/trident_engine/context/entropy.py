"""Cognitive Entropy Monitor.

Token count is necessary but insufficient. A small contradictory context
is more dangerous than a large coherent one.

Cognitive Complexity Score (CCS) metrics:
- contradiction_density: conflicting statements / total statements
- ambiguity_score: NER confidence < 0.7 or intent variance > 0.3
- temporal_consistency: 1 - (sequence violations / total events)
- cross_agent_conflict: ensemble variance > 0.15 or tool output mismatch

CCS thresholds gate autonomy:
- < 0.4: autonomous execution
- 0.4-0.6: verification amplification + log snapshot
- 0.6-0.8: workflow partitioning + invoke HITL
- > 0.8: freeze execution + kill switch evaluation

Playbook v8.0 (new subsystem, extends Part 5).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class EntropyAction(str, Enum):
    AUTONOMOUS = "autonomous_execution"
    VERIFY_AMPLIFY = "verification_amplification"
    PARTITION_HITL = "workflow_partitioning_hitl"
    FREEZE_KILLSWITCH = "freeze_execution_killswitch"


@dataclass
class EntropyThreshold:
    """CCS threshold with associated action."""

    name: str
    max_score: float
    action: EntropyAction


@dataclass
class EntropyMetrics:
    """Raw metrics that compose the Cognitive Complexity Score."""

    contradiction_density: float = 0.0  # conflicting_statements / total_statements
    ambiguity_score: float = 0.0        # NER_confidence < 0.7 or intent_variance > 0.3
    temporal_consistency: float = 1.0   # 1 - (sequence_violations / total_events)
    cross_agent_conflict: float = 0.0   # ensemble_variance > 0.15 or tool mismatch

    @property
    def ccs(self) -> float:
        """Cognitive Complexity Score: weighted combination of entropy metrics.

        Weights reflect failure severity from FMEA:
        - contradiction_density: 0.35 (highest — silent compression loss, RPN 225)
        - cross_agent_conflict: 0.25 (ensemble disagreement hidden, RPN 175)
        - ambiguity_score: 0.25 (cognitive entropy collapse, RPN 180)
        - temporal_inconsistency: 0.15 (state corruption, RPN 120)
        """
        temporal_entropy = 1.0 - self.temporal_consistency
        return (
            0.35 * self.contradiction_density
            + 0.25 * self.cross_agent_conflict
            + 0.25 * self.ambiguity_score
            + 0.15 * temporal_entropy
        )


@dataclass
class EntropySnapshot:
    """Point-in-time entropy measurement for audit logging."""

    session_id: str
    agent_id: str
    timestamp: float
    metrics: EntropyMetrics
    ccs: float
    action_taken: EntropyAction
    details: dict[str, Any] = field(default_factory=dict)


class CognitiveEntropyMonitor:
    """Monitors cognitive entropy across context assembly pipeline.

    Computes CCS at assembly time and gates autonomy accordingly.
    """

    DEFAULT_THRESHOLDS = [
        EntropyThreshold("autonomous", 0.4, EntropyAction.AUTONOMOUS),
        EntropyThreshold("elevated", 0.6, EntropyAction.VERIFY_AMPLIFY),
        EntropyThreshold("high", 0.8, EntropyAction.PARTITION_HITL),
        EntropyThreshold("critical", 1.0, EntropyAction.FREEZE_KILLSWITCH),
    ]

    def __init__(self, thresholds: list[EntropyThreshold] | None = None) -> None:
        self.thresholds = sorted(
            thresholds or self.DEFAULT_THRESHOLDS,
            key=lambda t: t.max_score,
        )
        self._history: list[EntropySnapshot] = []

    @classmethod
    def from_yaml(cls, path: str | Path) -> CognitiveEntropyMonitor:
        """Load thresholds from config artifact."""
        with open(path) as f:
            data = yaml.safe_load(f)

        ccs_config = data.get("cognitive_complexity_score", {})
        thresholds = []
        for name, cfg in ccs_config.get("thresholds", {}).items():
            max_score = cfg.get("max", cfg.get("above", 1.0))
            action = EntropyAction(cfg["action"])
            thresholds.append(EntropyThreshold(name, float(max_score), action))

        return cls(thresholds=thresholds)

    def evaluate(
        self,
        session_id: str,
        agent_id: str,
        metrics: EntropyMetrics,
        timestamp: float | None = None,
    ) -> EntropySnapshot:
        """Evaluate CCS and determine the action to take.

        Returns an EntropySnapshot with the score and gated action.
        """
        import time as _time
        ts = timestamp or _time.time()
        ccs = metrics.ccs
        action = self._resolve_action(ccs)

        snapshot = EntropySnapshot(
            session_id=session_id,
            agent_id=agent_id,
            timestamp=ts,
            metrics=metrics,
            ccs=round(ccs, 4),
            action_taken=action,
        )
        self._history.append(snapshot)

        if action != EntropyAction.AUTONOMOUS:
            logger.warning(
                "CCS elevated for %s/%s: %.4f → %s",
                session_id, agent_id, ccs, action.value,
            )

        return snapshot

    def check_contradictions(self, statements: list[dict[str, Any]]) -> float:
        """Compute contradiction density from a list of context statements.

        Each statement dict should have 'claim' and optional 'source', 'confidence'.
        Returns ratio of conflicting statement pairs to total statements.
        """
        if len(statements) < 2:
            return 0.0

        conflicts = 0
        for i, s1 in enumerate(statements):
            for s2 in statements[i + 1:]:
                if self._are_contradictory(s1, s2):
                    conflicts += 1

        max_pairs = len(statements) * (len(statements) - 1) / 2
        return conflicts / max_pairs if max_pairs > 0 else 0.0

    def check_ensemble_conflict(
        self,
        pyg_score: float,
        dgl_score: float,
        xgb_score: float,
        variance_threshold: float = 0.15,
    ) -> tuple[float, bool]:
        """Check cross-prong ensemble disagreement.

        Returns (variance, is_conflicting).
        """
        import numpy as np
        scores = np.array([pyg_score, dgl_score, xgb_score])
        variance = float(np.var(scores))
        return variance, variance > variance_threshold

    @property
    def recent_snapshots(self) -> list[EntropySnapshot]:
        return self._history[-20:]

    def _resolve_action(self, ccs: float) -> EntropyAction:
        for threshold in self.thresholds:
            if ccs <= threshold.max_score:
                return threshold.action
        return EntropyAction.FREEZE_KILLSWITCH

    @staticmethod
    def _are_contradictory(s1: dict[str, Any], s2: dict[str, Any]) -> bool:
        """Heuristic contradiction detection between two statements.

        Production version would use an NLI model. This is the structural scaffold.
        """
        # Placeholder: check for explicit negation markers
        c1 = s1.get("claim", "").lower()
        c2 = s2.get("claim", "").lower()

        negation_pairs = [
            ("available", "unavailable"),
            ("open", "closed"),
            ("in stock", "out of stock"),
            ("confirmed", "cancelled"),
            ("delivered", "not delivered"),
        ]
        for pos, neg in negation_pairs:
            if (pos in c1 and neg in c2) or (neg in c1 and pos in c2):
                return True
        return False
