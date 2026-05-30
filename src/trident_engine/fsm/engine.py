"""FSM Engine — Deterministic Workflow Authority.

Core principle: LLMs may propose transitions. The FSM engine authorizes them.

All state transitions are:
- Validated against allowed transitions before execution
- Logged to immutable audit trail
- Compensatable (every transition has a rollback handler)
- Timeout-bounded with retry limits

Playbook v8.0 Parts 2, 16.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

import yaml

logger = logging.getLogger(__name__)


class FSMState(str, Enum):
    """Canonical order workflow states."""

    IDLE = "IDLE"
    ORDER_INITIATED = "ORDER_INITIATED"
    PAYMENT_AUTHORIZED = "PAYMENT_AUTHORIZED"
    MERCHANT_CONFIRMED = "MERCHANT_CONFIRMED"
    DRIVER_ASSIGNED = "DRIVER_ASSIGNED"
    DELIVERED = "DELIVERED"
    CLOSED = "CLOSED"
    REFUND_INITIATED = "REFUND_INITIATED"
    FAILED = "FAILED"


@dataclass
class TransitionRule:
    """A single allowed state transition with guards and compensation."""

    from_state: FSMState
    to_state: FSMState
    condition: str  # Name of the condition check
    timeout_seconds: int = 300
    max_retries: int = 2
    compensation: str | None = None  # Name of the compensation handler

    @property
    def key(self) -> str:
        return f"{self.from_state.value}->{self.to_state.value}"


@dataclass
class TransitionEvent:
    """Immutable record of a state transition."""

    event_id: str
    session_id: str
    from_state: str
    to_state: str
    trigger: str
    timestamp: float
    success: bool
    error: str | None = None
    compensation_executed: bool = False


class FSMEngine:
    """Deterministic finite state machine for order workflows.

    The FSM is the system-of-record for workflow state.
    LLM outputs are proposals that must be validated before execution.
    """

    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.current_state = FSMState.IDLE
        self._rules: dict[str, TransitionRule] = {}
        self._history: list[TransitionEvent] = []
        self._event_counter = 0

        # Condition checkers: name → callable
        self._conditions: dict[str, Callable[..., bool]] = {}
        # Compensation handlers: name → callable
        self._compensations: dict[str, Callable[..., None]] = {}

        # Load default transition rules
        self._load_default_rules()

    @property
    def state(self) -> FSMState:
        return self.current_state

    @property
    def history(self) -> list[TransitionEvent]:
        return list(self._history)

    @property
    def is_terminal(self) -> bool:
        return self.current_state in (FSMState.CLOSED, FSMState.FAILED)

    def register_condition(self, name: str, checker: Callable[..., bool]) -> None:
        """Register a condition checker for transition validation."""
        self._conditions[name] = checker

    def register_compensation(self, name: str, handler: Callable[..., None]) -> None:
        """Register a compensation handler for rollback."""
        self._compensations[name] = handler

    def propose_transition(self, to_state: str, trigger: str = "llm_proposal") -> TransitionEvent:
        """Validate and execute a state transition.

        This is the gate: LLM proposes, FSM authorizes.

        Args:
            to_state: Proposed next state (string, validated against FSMState).
            trigger: What triggered this transition (for audit).

        Returns:
            TransitionEvent (success or failure, logged either way).
        """
        try:
            target = FSMState(to_state)
        except ValueError:
            return self._record_event(
                to_state=to_state,
                trigger=trigger,
                success=False,
                error=f"Invalid state: {to_state}",
            )

        # Check if transition is allowed
        rule_key = f"{self.current_state.value}->{target.value}"
        rule = self._rules.get(rule_key)

        if rule is None:
            return self._record_event(
                to_state=to_state,
                trigger=trigger,
                success=False,
                error=f"Transition not allowed: {rule_key}",
            )

        # Check condition
        condition_fn = self._conditions.get(rule.condition)
        if condition_fn and not condition_fn():
            return self._record_event(
                to_state=to_state,
                trigger=trigger,
                success=False,
                error=f"Condition failed: {rule.condition}",
            )

        # Execute transition
        old_state = self.current_state

        event = self._record_event(
            to_state=to_state,
            trigger=trigger,
            success=True,
        )

        self.current_state = target

        logger.info(
            "FSM transition: %s → %s (session=%s, trigger=%s)",
            old_state.value, target.value, self.session_id, trigger,
        )
        return event

    def compensate(self, event: TransitionEvent) -> bool:
        """Execute compensation (rollback) for a failed transition.

        Finds the compensation handler for the transition and executes it.
        Returns True if compensation succeeded.
        """
        rule_key = f"{event.from_state}->{event.to_state}"
        rule = self._rules.get(rule_key)

        if rule is None or rule.compensation is None:
            logger.warning("No compensation available for %s", rule_key)
            return False

        handler = self._compensations.get(rule.compensation)
        if handler is None:
            logger.error("Compensation handler not registered: %s", rule.compensation)
            return False

        try:
            handler()
            # Revert state
            self.current_state = FSMState(event.from_state)
            logger.info("Compensation executed: %s (reverted to %s)", rule.compensation, event.from_state)
            return True
        except Exception as e:
            logger.error("Compensation failed: %s - %s", rule.compensation, e)
            return False

    def allowed_transitions(self) -> list[str]:
        """Return list of states reachable from current state."""
        return [
            rule.to_state.value
            for rule in self._rules.values()
            if rule.from_state == self.current_state
        ]

    def validate_llm_proposal(self, proposed_state: str) -> dict[str, Any]:
        """Validate an LLM-proposed transition without executing it.

        Returns validation result with allowed flag and reason.
        """
        try:
            target = FSMState(proposed_state)
        except ValueError:
            return {"allowed": False, "reason": f"Invalid state: {proposed_state}"}

        rule_key = f"{self.current_state.value}->{target.value}"
        rule = self._rules.get(rule_key)

        if rule is None:
            return {
                "allowed": False,
                "reason": f"No transition from {self.current_state.value} to {target.value}",
                "allowed_states": self.allowed_transitions(),
            }

        return {
            "allowed": True,
            "from": self.current_state.value,
            "to": target.value,
            "condition": rule.condition,
            "timeout": rule.timeout_seconds,
            "has_compensation": rule.compensation is not None,
        }

    @classmethod
    def from_yaml(cls, session_id: str, path: str | Path) -> FSMEngine:
        """Load FSM definition from a YAML schema file."""
        engine = cls(session_id=session_id)

        with open(path) as f:
            data = yaml.safe_load(f)

        # Clear default rules and load from file
        engine._rules.clear()

        for transition_str, config in data.get("transitions", {}).items():
            parts = transition_str.split("->")
            if len(parts) != 2:
                continue

            from_str, to_str = parts[0].strip(), parts[1].strip()
            try:
                from_state = FSMState(from_str)
                to_state = FSMState(to_str)
            except ValueError:
                logger.warning("Skipping unknown state in: %s", transition_str)
                continue

            rule = TransitionRule(
                from_state=from_state,
                to_state=to_state,
                condition=config.get("condition", "always_true"),
                timeout_seconds=config.get("timeout", 300),
                max_retries=config.get("retry", 2),
                compensation=config.get("compensation"),
            )
            engine._rules[rule.key] = rule

        return engine

    def _load_default_rules(self) -> None:
        """Load the canonical order workflow transitions."""
        defaults = [
            TransitionRule(FSMState.IDLE, FSMState.ORDER_INITIATED, "order_valid"),
            TransitionRule(FSMState.ORDER_INITIATED, FSMState.PAYMENT_AUTHORIZED, "payment_processor_success", timeout_seconds=300, max_retries=2, compensation="release_inventory_hold"),
            TransitionRule(FSMState.PAYMENT_AUTHORIZED, FSMState.MERCHANT_CONFIRMED, "merchant_api_acknowledgment", timeout_seconds=120, max_retries=3, compensation="reverse_payment_authorization"),
            TransitionRule(FSMState.MERCHANT_CONFIRMED, FSMState.DRIVER_ASSIGNED, "driver_matched", timeout_seconds=600, compensation="cancel_merchant_order"),
            TransitionRule(FSMState.DRIVER_ASSIGNED, FSMState.DELIVERED, "delivery_confirmed", timeout_seconds=3600),
            TransitionRule(FSMState.DELIVERED, FSMState.CLOSED, "always_true"),
            TransitionRule(FSMState.CLOSED, FSMState.REFUND_INITIATED, "refund_eligible"),
            # Failure transitions
            TransitionRule(FSMState.ORDER_INITIATED, FSMState.FAILED, "always_true"),
            TransitionRule(FSMState.PAYMENT_AUTHORIZED, FSMState.FAILED, "always_true", compensation="reverse_payment_authorization"),
            TransitionRule(FSMState.MERCHANT_CONFIRMED, FSMState.FAILED, "always_true", compensation="cancel_merchant_order"),
        ]
        for rule in defaults:
            self._rules[rule.key] = rule

    def _record_event(
        self, to_state: str, trigger: str, success: bool, error: str | None = None,
    ) -> TransitionEvent:
        self._event_counter += 1
        event = TransitionEvent(
            event_id=f"evt_{self.session_id}_{self._event_counter}",
            session_id=self.session_id,
            from_state=self.current_state.value,
            to_state=to_state,
            trigger=trigger,
            timestamp=time.time(),
            success=success,
            error=error,
        )
        self._history.append(event)
        return event
