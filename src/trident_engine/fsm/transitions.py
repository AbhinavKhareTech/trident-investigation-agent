"""Transition validation for FSM engine.

Validates LLM-proposed state transitions before execution.
All validation is deterministic — no LLM in the loop for state management.

Playbook v8.0 Part 16.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from trident_engine.fsm.engine import FSMEngine, FSMState, TransitionEvent

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of validating an LLM-proposed transition."""

    allowed: bool
    from_state: str
    proposed_state: str
    reason: str
    allowed_transitions: list[str] = field(default_factory=list)
    has_compensation: bool = False
    timeout_seconds: int = 0


class TransitionValidator:
    """Validates LLM-proposed FSM transitions and enforces temporal guards.

    The validator sits between LLM output and FSM execution:
    LLM proposes → Validator checks → FSM executes (or rejects)

    Checks:
    1. Proposed state is a valid FSMState
    2. Transition is allowed from current state
    3. Condition is met (if registered)
    4. Timeout hasn't expired since last transition
    5. Retry limit not exceeded for repeated failures
    """

    def __init__(self, engine: FSMEngine) -> None:
        self.engine = engine
        self._retry_counts: dict[str, int] = {}
        self._last_transition_time: float = time.time()

    def validate(self, proposed_state: str) -> ValidationResult:
        """Validate a proposed transition without executing it.

        Returns ValidationResult with detailed reason for allow/deny.
        """
        # Check 1: Valid state
        try:
            target = FSMState(proposed_state)
        except ValueError:
            return ValidationResult(
                allowed=False,
                from_state=self.engine.current_state.value,
                proposed_state=proposed_state,
                reason=f"Invalid state: '{proposed_state}'. Valid states: {[s.value for s in FSMState]}",
            )

        # Check 2: Use engine's built-in validation
        result = self.engine.validate_llm_proposal(proposed_state)

        if not result["allowed"]:
            return ValidationResult(
                allowed=False,
                from_state=self.engine.current_state.value,
                proposed_state=proposed_state,
                reason=result["reason"],
                allowed_transitions=result.get("allowed_states", []),
            )

        # Check 3: Retry limit for this transition
        transition_key = f"{self.engine.current_state.value}->{proposed_state}"
        retries = self._retry_counts.get(transition_key, 0)
        max_retries = result.get("timeout", 300) // 60  # Rough: 1 retry per minute of timeout
        max_retries = max(max_retries, 2)

        if retries >= max_retries:
            return ValidationResult(
                allowed=False,
                from_state=self.engine.current_state.value,
                proposed_state=proposed_state,
                reason=f"Retry limit exceeded for {transition_key}: {retries}/{max_retries}",
            )

        return ValidationResult(
            allowed=True,
            from_state=self.engine.current_state.value,
            proposed_state=proposed_state,
            reason="Transition allowed",
            has_compensation=result.get("has_compensation", False),
            timeout_seconds=result.get("timeout", 300),
        )

    def validate_and_execute(
        self, proposed_state: str, trigger: str = "llm_proposal",
    ) -> tuple[ValidationResult, TransitionEvent | None]:
        """Validate and execute if allowed. Returns both validation and event."""
        validation = self.validate(proposed_state)

        if not validation.allowed:
            logger.warning(
                "Transition rejected: %s → %s (%s)",
                validation.from_state, proposed_state, validation.reason,
            )
            return validation, None

        event = self.engine.propose_transition(proposed_state, trigger)
        transition_key = f"{validation.from_state}->{proposed_state}"

        if event.success:
            self._retry_counts.pop(transition_key, None)
            self._last_transition_time = time.time()
        else:
            self._retry_counts[transition_key] = self._retry_counts.get(transition_key, 0) + 1

        return validation, event

    def get_allowed_actions(self) -> dict[str, Any]:
        """Return allowed transitions from current state for LLM guidance.

        Inject this into the Execution Plane to constrain LLM proposals.
        """
        allowed = self.engine.allowed_transitions()
        return {
            "current_state": self.engine.current_state.value,
            "allowed_transitions": allowed,
            "is_terminal": self.engine.is_terminal,
            "instruction": (
                f"You are in state {self.engine.current_state.value}. "
                f"You may only propose transitions to: {allowed}. "
                "Any other transition will be rejected by the FSM engine."
            ),
        }
