"""Deterministic Workflow Authority.

LLMs may propose transitions. The FSM engine authorizes them.

Never allow prompt memory, conversational reasoning, or hidden chain-of-thought
to become system-of-record workflow state.

Playbook v8.0 Parts 2, 16.
"""

from trident_engine.fsm.engine import FSMEngine, FSMState
from trident_engine.fsm.transitions import TransitionValidator

__all__ = ["FSMEngine", "FSMState", "TransitionValidator"]
