"""Token budget enforcement with graceful degradation.

Per-agent hard caps with sequential degradation ladder.
Session-level budget sums to exactly 100%.

Playbook v8.0 Part 32.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class DegradationAction(str, Enum):
    """Sequential degradation actions. Order matters — never skip steps."""

    REDUCE_K = "reduce_k"           # RAG top-K: 5 → 3 → 1
    COMPRESS = "compress"           # Abstractive summarization
    LOSSY_TOP3 = "lossy_top3"       # Graph signals: top-3 scores only
    REDUCE_WINDOW = "reduce_window" # History: 3-turn → 1-turn
    SUMMARIZE = "summarize"         # Aggressive summarization
    DROP_FEWSHOT = "drop_fewshot"   # Remove few-shot examples
    SIMPLIFY_SCHEMA = "simplify_schema"  # Minimal output schema
    ESCALATE_HITL = "escalate_hitl" # Human takes over


@dataclass
class CategoryBudget:
    """Budget allocation for a single context category."""

    name: str
    percentage: float
    is_static: bool
    degradation_actions: list[DegradationAction]
    never_degrade: bool = False

    @property
    def can_degrade(self) -> bool:
        return not self.never_degrade and len(self.degradation_actions) > 0


@dataclass
class TokenBudget:
    """Per-agent token budget with category allocations."""

    agent_id: str
    model_tier: str  # frontier, strong, fast
    hard_cap: int
    categories: list[CategoryBudget] = field(default_factory=list)

    def __post_init__(self) -> None:
        total_pct = sum(c.percentage for c in self.categories)
        if self.categories and abs(total_pct - 100.0) > 0.5:
            raise ValueError(
                f"Budget for {self.agent_id}: categories sum to {total_pct}%, must be ~100%"
            )

    def tokens_for(self, category_name: str) -> int:
        """Get hard token limit for a category."""
        for cat in self.categories:
            if cat.name == category_name:
                return int(self.hard_cap * cat.percentage / 100.0)
        raise KeyError(f"Unknown category: {category_name}")

    @classmethod
    def from_yaml(cls, path: str | Path) -> TokenBudget:
        """Load budget from YAML config artifact."""
        with open(path) as f:
            data = yaml.safe_load(f)

        categories = []
        for name, alloc in data.get("allocation", {}).items():
            actions = []
            for a in alloc.get("degrade", []) or []:
                try:
                    actions.append(DegradationAction(a))
                except ValueError:
                    logger.warning("Unknown degradation action: %s", a)

            categories.append(CategoryBudget(
                name=name,
                percentage=alloc["pct"],
                is_static=alloc.get("type", "dynamic") == "static",
                degradation_actions=actions,
                never_degrade=alloc.get("degrade") == "never",
            ))

        return cls(
            agent_id=data["agent"],
            model_tier=data["model_tier"],
            hard_cap=data["hard_cap_tokens"],
            categories=categories,
        )


@dataclass
class BudgetState:
    """Runtime budget tracking for a single agent invocation."""

    budget: TokenBudget
    used: dict[str, int] = field(default_factory=dict)
    degradations_applied: list[str] = field(default_factory=list)
    _degradation_step: int = 0

    @property
    def total_used(self) -> int:
        return sum(self.used.values())

    @property
    def remaining(self) -> int:
        return self.budget.hard_cap - self.total_used

    @property
    def utilization(self) -> float:
        return self.total_used / self.budget.hard_cap if self.budget.hard_cap > 0 else 0.0

    def try_allocate(self, category_name: str, tokens: int) -> bool:
        """Try to allocate tokens for a category. Returns False if over budget."""
        limit = self.budget.tokens_for(category_name)
        current = self.used.get(category_name, 0)
        if current + tokens > limit:
            return False
        if self.total_used + tokens > self.budget.hard_cap:
            return False
        self.used[category_name] = current + tokens
        return True

    def force_allocate(self, category_name: str, tokens: int) -> None:
        """Allocate without checking limits (for static/critical blocks)."""
        current = self.used.get(category_name, 0)
        self.used[category_name] = current + tokens

    def category_remaining(self, category_name: str) -> int:
        limit = self.budget.tokens_for(category_name)
        used = self.used.get(category_name, 0)
        return max(0, limit - used)


class TokenBudgetEnforcer:
    """Enforces token budgets across all agents in a session.

    Session budget sums to 100%:
    - Session Supervisor:        4,000 (16.3%)
    - Domain Coordinators (×3):  3,000 each (12.2% each)
    - Settlement Agent:          2,000 (8.1%)
    - Verification Orchestrator: 2,000 (8.1%)
    - Reserved Safety Pool:      7,600 (30.9%)
    - TOTAL:                    24,600 (100.0%)
    """

    SESSION_HARD_CAP = 24_600

    def __init__(self) -> None:
        self._agent_budgets: dict[str, TokenBudget] = {}
        self._active_states: dict[str, BudgetState] = {}

    def register_agent(self, budget: TokenBudget) -> None:
        """Register an agent's budget. Call at session start."""
        self._agent_budgets[budget.agent_id] = budget

    def start_invocation(self, agent_id: str) -> BudgetState:
        """Begin tracking for a single agent invocation."""
        budget = self._agent_budgets.get(agent_id)
        if budget is None:
            raise KeyError(f"No budget registered for agent: {agent_id}")
        state = BudgetState(budget=budget)
        self._active_states[agent_id] = state
        return state

    def get_state(self, agent_id: str) -> BudgetState | None:
        return self._active_states.get(agent_id)

    @property
    def session_tokens_used(self) -> int:
        return sum(s.total_used for s in self._active_states.values())

    @property
    def session_utilization(self) -> float:
        return self.session_tokens_used / self.SESSION_HARD_CAP

    def check_anomaly(self, threshold_multiplier: float = 2.0) -> list[str]:
        """Detect spend anomalies. Returns list of agents over threshold."""
        anomalies = []
        for agent_id, state in self._active_states.items():
            if state.utilization > (1.0 / threshold_multiplier) * threshold_multiplier:
                anomalies.append(agent_id)
        return anomalies

    def get_degradation_plan(self, agent_id: str) -> list[DegradationAction]:
        """Get the next degradation action for an over-budget agent.

        Degradation ladder is sequential — never skip steps:
        1. Reduce RAG top-K (5→3→1)        ~560 tokens recovered
        2. Compress historical state         ~400 tokens recovered
        3. Lossy graph signals (top-3)       ~40 tokens recovered
        4. Drop few-shot examples            ~200 tokens recovered
        5. Simplify output schema            ~100 tokens recovered
        6. Escalate to HITL                  human takes over
        """
        state = self._active_states.get(agent_id)
        if state is None:
            return []

        # Collect all degradation actions across degradable categories, in order
        ladder: list[DegradationAction] = [
            DegradationAction.REDUCE_K,
            DegradationAction.COMPRESS,
            DegradationAction.REDUCE_WINDOW,
            DegradationAction.SUMMARIZE,
            DegradationAction.LOSSY_TOP3,
            DegradationAction.DROP_FEWSHOT,
            DegradationAction.SIMPLIFY_SCHEMA,
            DegradationAction.ESCALATE_HITL,
        ]

        # Return only actions not yet applied
        remaining = [a for a in ladder if a.value not in state.degradations_applied]
        return remaining

    def apply_degradation(self, agent_id: str, action: DegradationAction) -> None:
        """Record that a degradation action was applied."""
        state = self._active_states.get(agent_id)
        if state:
            state.degradations_applied.append(action.value)
            logger.info(
                "Degradation applied for %s: %s (step %d)",
                agent_id, action.value, len(state.degradations_applied),
            )

    def summary(self) -> dict[str, Any]:
        """Session budget summary for observability."""
        return {
            "session_hard_cap": self.SESSION_HARD_CAP,
            "session_used": self.session_tokens_used,
            "session_utilization": round(self.session_utilization, 4),
            "agents": {
                agent_id: {
                    "hard_cap": state.budget.hard_cap,
                    "used": state.total_used,
                    "utilization": round(state.utilization, 4),
                    "degradations": state.degradations_applied,
                }
                for agent_id, state in self._active_states.items()
            },
        }
