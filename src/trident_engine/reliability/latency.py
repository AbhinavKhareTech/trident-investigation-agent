"""Latency budget decomposition and monitoring.

Total TTFT SLA: < 2,000ms

Phase breakdown:
- Intent + CCS:               60ms (cold) / 60ms (hot)
- Hybrid retrieval + Rerank: 220ms / 150ms
- Dedup + Compression:       170ms / 50ms
- Assembly + Handles:         80ms / 20ms
- LLM TTFT (Frontier):      900ms / 900ms
- Total:                   1,430ms / 1,180ms

Playbook v8.0 Part 9.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class LatencyPhase:
    """A single phase in the latency budget."""

    name: str
    budget_cold_ms: float
    budget_hot_ms: float
    fallback: str  # What to do if this phase is slow

    def is_over_budget(self, elapsed_ms: float, is_cold: bool = True) -> bool:
        budget = self.budget_cold_ms if is_cold else self.budget_hot_ms
        return elapsed_ms > budget


@dataclass
class LatencyMeasurement:
    """Measurement of a single phase execution."""

    phase: str
    elapsed_ms: float
    is_cold: bool
    over_budget: bool
    timestamp: float


class LatencyBudget:
    """Tracks latency budget across the context assembly + LLM pipeline.

    Provides per-phase budgets, real-time tracking, and SLA enforcement.
    """

    SLA_MS = 2000.0

    DEFAULT_PHASES = [
        LatencyPhase("intent_ccs", 60, 60, "regex_matcher"),
        LatencyPhase("retrieval_rerank", 220, 150, "bm25_only"),
        LatencyPhase("dedup_compression", 170, 50, "skip_dedup"),
        LatencyPhase("assembly_handles", 80, 20, "minimal_provenance"),
        LatencyPhase("llm_ttft", 900, 900, "secondary_provider"),
    ]

    def __init__(self, phases: list[LatencyPhase] | None = None) -> None:
        self._phases = {p.name: p for p in (phases or self.DEFAULT_PHASES)}
        self._measurements: list[LatencyMeasurement] = []
        self._active_timers: dict[str, float] = {}  # phase_name → start_time

    @property
    def total_budget_cold_ms(self) -> float:
        return sum(p.budget_cold_ms for p in self._phases.values())

    @property
    def total_budget_hot_ms(self) -> float:
        return sum(p.budget_hot_ms for p in self._phases.values())

    def start_phase(self, phase_name: str) -> None:
        """Start timing a phase."""
        if phase_name not in self._phases:
            logger.warning("Unknown latency phase: %s", phase_name)
        self._active_timers[phase_name] = time.time()

    def end_phase(self, phase_name: str, is_cold: bool = True) -> LatencyMeasurement:
        """End timing a phase and record the measurement."""
        start = self._active_timers.pop(phase_name, None)
        if start is None:
            logger.warning("Phase %s was not started", phase_name)
            elapsed_ms = 0.0
        else:
            elapsed_ms = (time.time() - start) * 1000

        phase = self._phases.get(phase_name)
        over_budget = phase.is_over_budget(elapsed_ms, is_cold) if phase else False

        measurement = LatencyMeasurement(
            phase=phase_name,
            elapsed_ms=round(elapsed_ms, 2),
            is_cold=is_cold,
            over_budget=over_budget,
            timestamp=time.time(),
        )
        self._measurements.append(measurement)

        if over_budget and phase:
            logger.warning(
                "Phase %s over budget: %.1fms (budget: %.1fms) — fallback: %s",
                phase_name, elapsed_ms,
                phase.budget_cold_ms if is_cold else phase.budget_hot_ms,
                phase.fallback,
            )

        return measurement

    def check_sla(self, is_cold: bool = True) -> dict[str, Any]:
        """Check if total latency is within SLA."""
        total_ms = sum(m.elapsed_ms for m in self._measurements)
        over_budget_phases = [m for m in self._measurements if m.over_budget]

        return {
            "total_ms": round(total_ms, 2),
            "sla_ms": self.SLA_MS,
            "within_sla": total_ms <= self.SLA_MS,
            "headroom_ms": round(self.SLA_MS - total_ms, 2),
            "over_budget_phases": [
                {"phase": m.phase, "elapsed_ms": m.elapsed_ms}
                for m in over_budget_phases
            ],
            "phase_breakdown": {
                m.phase: m.elapsed_ms for m in self._measurements
            },
        }

    def get_fallback(self, phase_name: str) -> str | None:
        """Get the fallback strategy for a slow phase."""
        phase = self._phases.get(phase_name)
        return phase.fallback if phase else None

    def remaining_budget_ms(self) -> float:
        """How much latency budget remains for unfinished phases."""
        elapsed = sum(m.elapsed_ms for m in self._measurements)
        return max(0, self.SLA_MS - elapsed)

    def reset(self) -> None:
        """Reset measurements for a new request."""
        self._measurements.clear()
        self._active_timers.clear()

    def summary(self) -> dict[str, Any]:
        """Summary of all latency phases for observability."""
        return {
            "sla_ms": self.SLA_MS,
            "budget_cold_ms": self.total_budget_cold_ms,
            "budget_hot_ms": self.total_budget_hot_ms,
            "phases": {
                name: {
                    "cold_budget_ms": p.budget_cold_ms,
                    "hot_budget_ms": p.budget_hot_ms,
                    "fallback": p.fallback,
                }
                for name, p in self._phases.items()
            },
        }
