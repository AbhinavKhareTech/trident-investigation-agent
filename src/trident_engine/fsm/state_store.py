"""Persistent FSM state storage.

FSM state is the system-of-record for workflow progress.
It must survive process restarts, provider failovers, and session resumption.

Production backend: Redis or PostgreSQL.
This implementation: in-memory with serialization interface.

Playbook v8.0 Part 16.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any

from trident_engine.fsm.engine import FSMState, TransitionEvent

logger = logging.getLogger(__name__)


@dataclass
class PersistedState:
    """Serializable FSM state for storage."""

    session_id: str
    current_state: str
    history: list[dict[str, Any]]
    created_at: float
    updated_at: float
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> str:
        return json.dumps({
            "session_id": self.session_id,
            "current_state": self.current_state,
            "history": self.history,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "metadata": self.metadata,
        }, default=str)

    @classmethod
    def from_json(cls, data: str) -> PersistedState:
        d = json.loads(data)
        return cls(**d)


class FSMStateStore:
    """In-memory FSM state store with serialization interface.

    Production: swap to Redis/PostgreSQL by implementing get/put/delete.
    """

    def __init__(self) -> None:
        self._store: dict[str, PersistedState] = {}

    def save(
        self,
        session_id: str,
        current_state: FSMState,
        history: list[TransitionEvent],
        metadata: dict[str, Any] | None = None,
    ) -> PersistedState:
        """Persist current FSM state."""
        now = time.time()
        existing = self._store.get(session_id)

        persisted = PersistedState(
            session_id=session_id,
            current_state=current_state.value,
            history=[
                {
                    "event_id": e.event_id,
                    "from_state": e.from_state,
                    "to_state": e.to_state,
                    "trigger": e.trigger,
                    "timestamp": e.timestamp,
                    "success": e.success,
                    "error": e.error,
                }
                for e in history
            ],
            created_at=existing.created_at if existing else now,
            updated_at=now,
            metadata=metadata or {},
        )
        self._store[session_id] = persisted
        return persisted

    def load(self, session_id: str) -> PersistedState | None:
        return self._store.get(session_id)

    def delete(self, session_id: str) -> bool:
        return self._store.pop(session_id, None) is not None

    def list_active(self) -> list[str]:
        """List session IDs with non-terminal states."""
        terminal = {FSMState.CLOSED.value, FSMState.FAILED.value}
        return [
            sid for sid, state in self._store.items()
            if state.current_state not in terminal
        ]

    @property
    def total_sessions(self) -> int:
        return len(self._store)
