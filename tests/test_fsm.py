"""Tests for FSM package — deterministic workflow authority."""

from __future__ import annotations

import pytest

from trident_engine.fsm.engine import FSMEngine, FSMState, TransitionEvent
from trident_engine.fsm.transitions import TransitionValidator
from trident_engine.fsm.state_store import FSMStateStore


class TestFSMEngine:
    def test_initial_state(self):
        engine = FSMEngine("session_1")
        assert engine.state == FSMState.IDLE

    def test_valid_transition(self):
        engine = FSMEngine("session_1")
        event = engine.propose_transition("ORDER_INITIATED", "user_action")
        assert event.success is True
        assert engine.state == FSMState.ORDER_INITIATED

    def test_invalid_transition(self):
        engine = FSMEngine("session_1")
        event = engine.propose_transition("DELIVERED", "llm_proposal")
        assert event.success is False
        assert engine.state == FSMState.IDLE  # Unchanged

    def test_invalid_state_name(self):
        engine = FSMEngine("session_1")
        event = engine.propose_transition("NONEXISTENT", "llm_proposal")
        assert event.success is False

    def test_canonical_workflow(self):
        engine = FSMEngine("session_1")
        # Register a permissive condition for testing
        engine.register_condition("order_valid", lambda: True)
        engine.register_condition("payment_processor_success", lambda: True)
        engine.register_condition("merchant_api_acknowledgment", lambda: True)
        engine.register_condition("driver_matched", lambda: True)
        engine.register_condition("delivery_confirmed", lambda: True)
        engine.register_condition("always_true", lambda: True)

        states = [
            "ORDER_INITIATED",
            "PAYMENT_AUTHORIZED",
            "MERCHANT_CONFIRMED",
            "DRIVER_ASSIGNED",
            "DELIVERED",
            "CLOSED",
        ]
        for state in states:
            event = engine.propose_transition(state)
            assert event.success is True, f"Failed at {state}: {event.error}"

        assert engine.state == FSMState.CLOSED
        assert engine.is_terminal is True

    def test_allowed_transitions(self):
        engine = FSMEngine("session_1")
        allowed = engine.allowed_transitions()
        assert "ORDER_INITIATED" in allowed
        assert "DELIVERED" not in allowed

    def test_validate_llm_proposal(self):
        engine = FSMEngine("session_1")
        result = engine.validate_llm_proposal("ORDER_INITIATED")
        assert result["allowed"] is True
        result = engine.validate_llm_proposal("CLOSED")
        assert result["allowed"] is False

    def test_history_tracking(self):
        engine = FSMEngine("session_1")
        engine.propose_transition("ORDER_INITIATED")
        engine.propose_transition("DELIVERED")  # Invalid — still logged
        assert len(engine.history) == 2

    def test_compensation(self):
        engine = FSMEngine("session_1")
        engine.register_condition("order_valid", lambda: True)
        engine.register_condition("payment_processor_success", lambda: True)
        engine.register_compensation("release_inventory_hold", lambda: None)

        engine.propose_transition("ORDER_INITIATED")
        event = engine.propose_transition("PAYMENT_AUTHORIZED")
        assert event.success is True

        # Compensate
        success = engine.compensate(event)
        assert success is True
        assert engine.state == FSMState.ORDER_INITIATED  # Rolled back


class TestTransitionValidator:
    def test_validate_allowed(self):
        engine = FSMEngine("s1")
        validator = TransitionValidator(engine)
        result = validator.validate("ORDER_INITIATED")
        assert result.allowed is True

    def test_validate_not_allowed(self):
        engine = FSMEngine("s1")
        validator = TransitionValidator(engine)
        result = validator.validate("CLOSED")
        assert result.allowed is False

    def test_validate_and_execute(self):
        engine = FSMEngine("s1")
        validator = TransitionValidator(engine)
        validation, event = validator.validate_and_execute("ORDER_INITIATED")
        assert validation.allowed is True
        assert event is not None
        assert event.success is True
        assert engine.state == FSMState.ORDER_INITIATED

    def test_get_allowed_actions(self):
        engine = FSMEngine("s1")
        validator = TransitionValidator(engine)
        actions = validator.get_allowed_actions()
        assert actions["current_state"] == "IDLE"
        assert "ORDER_INITIATED" in actions["allowed_transitions"]


class TestFSMStateStore:
    def test_save_and_load(self):
        store = FSMStateStore()
        store.save("s1", FSMState.ORDER_INITIATED, [])
        loaded = store.load("s1")
        assert loaded is not None
        assert loaded.current_state == "ORDER_INITIATED"

    def test_delete(self):
        store = FSMStateStore()
        store.save("s1", FSMState.IDLE, [])
        assert store.delete("s1") is True
        assert store.load("s1") is None

    def test_list_active(self):
        store = FSMStateStore()
        store.save("s1", FSMState.ORDER_INITIATED, [])
        store.save("s2", FSMState.CLOSED, [])
        store.save("s3", FSMState.DRIVER_ASSIGNED, [])
        active = store.list_active()
        assert "s1" in active
        assert "s3" in active
        assert "s2" not in active  # CLOSED is terminal
