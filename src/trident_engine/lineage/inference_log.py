"""Append-only immutable inference log.

Every LLM inference is logged with:
- context_hash: SHA-256 of the assembled reasoning plane
- model_version: which model produced the output
- business_rules_version: which rules were active
- output_hash: SHA-256 of the LLM response
- provenance_refs: which data sources contributed

Records are never modified or deleted.
Production: S3 + Glacier with WORM (Write Once Read Many).
This implementation: in-memory append-only list.

Playbook v8.0 Part 26.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class InferenceRecord:
    """Immutable inference record. Frozen dataclass = cannot be modified after creation."""

    record_id: str
    session_id: str
    agent_id: str
    timestamp: float
    context_hash: str
    model_version: str
    business_rules_version: str
    output_hash: str
    provenance_refs: tuple[str, ...]  # Tuple for immutability
    token_budget_used: int = 0
    entropy_score: float = 0.0
    latency_ms: float = 0.0
    metadata: tuple[tuple[str, Any], ...] = ()  # Tuple of pairs for immutability


class InferenceLog:
    """Append-only inference log. Records cannot be modified or deleted."""

    def __init__(self) -> None:
        self._records: list[InferenceRecord] = []
        self._counter = 0
        self._index_by_session: dict[str, list[int]] = {}
        self._index_by_agent: dict[str, list[int]] = {}

    @property
    def total_records(self) -> int:
        return len(self._records)

    def append(
        self,
        session_id: str,
        agent_id: str,
        context_hash: str,
        model_version: str,
        business_rules_version: str,
        output_hash: str,
        provenance_refs: list[str],
        token_budget_used: int = 0,
        entropy_score: float = 0.0,
        latency_ms: float = 0.0,
        metadata: dict[str, Any] | None = None,
    ) -> InferenceRecord:
        """Append an inference record. Returns the immutable record."""
        self._counter += 1
        record = InferenceRecord(
            record_id=f"inf_{self._counter:06d}",
            session_id=session_id,
            agent_id=agent_id,
            timestamp=time.time(),
            context_hash=context_hash,
            model_version=model_version,
            business_rules_version=business_rules_version,
            output_hash=output_hash,
            provenance_refs=tuple(provenance_refs),
            token_budget_used=token_budget_used,
            entropy_score=entropy_score,
            latency_ms=latency_ms,
            metadata=tuple((metadata or {}).items()),
        )

        idx = len(self._records)
        self._records.append(record)
        self._index_by_session.setdefault(session_id, []).append(idx)
        self._index_by_agent.setdefault(agent_id, []).append(idx)

        return record

    def query_by_session(self, session_id: str) -> list[InferenceRecord]:
        indices = self._index_by_session.get(session_id, [])
        return [self._records[i] for i in indices]

    def query_by_agent(self, agent_id: str) -> list[InferenceRecord]:
        indices = self._index_by_agent.get(agent_id, [])
        return [self._records[i] for i in indices]

    def query_by_provenance(self, ref_id: str) -> list[InferenceRecord]:
        """Find all inferences that used a specific provenance reference."""
        return [r for r in self._records if ref_id in r.provenance_refs]

    def verify_integrity(self) -> dict[str, Any]:
        """Verify log integrity: no gaps, no modifications."""
        issues = []
        for i, record in enumerate(self._records):
            expected_id = f"inf_{i + 1:06d}"
            if record.record_id != expected_id:
                issues.append(f"Record {i}: expected {expected_id}, got {record.record_id}")

        return {
            "total_records": len(self._records),
            "integrity_ok": len(issues) == 0,
            "issues": issues,
        }

    @staticmethod
    def hash_output(output: str) -> str:
        return hashlib.sha256(output.encode()).hexdigest()
