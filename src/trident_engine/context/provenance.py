"""Provenance reference handles and lineage registry.

In-context provenance metadata costs 8-12% token overhead per chunk.
Reference handles cost ~1.2%.

In Reasoning Plane: REF_442 (~6 tokens)
In Audit Plane: Full lineage (source_doc → ingestion_batch → transform_job
    → embedding_model_version → chunk_id → decision_id)

Playbook v8.0 Part 26 (Data Lineage and Provenance Architecture).
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ProvenanceHandle:
    """Lightweight reference for the Reasoning Plane.

    Only ~6 tokens in context: "REF_442"
    Full lineage stored in Audit Plane via ProvenanceRegistry.
    """

    ref_id: str  # e.g., "REF_442"
    source_type: str  # "rag_chunk", "graph_embedding", "business_rule", "user_input"

    def __str__(self) -> str:
        return self.ref_id

    @property
    def context_token_cost(self) -> int:
        """Estimated token cost when injected into reasoning context."""
        return 2  # REF_xxx is roughly 2 tokens


@dataclass
class LineageRecord:
    """Full provenance chain for a single data source. Stored in Audit Plane only.

    Forward query: source_doc_id → all downstream decisions
    Backward query: decision_id → all contributing sources + confidence
    """

    ref_id: str
    source_doc_id: str | None = None
    ingestion_batch: str | None = None
    transformation_job: str | None = None
    embedding_model_version: str | None = None
    chunk_id: str | None = None
    confidence: float | None = None
    timestamp: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()


class ProvenanceRegistry:
    """Registry mapping reference handles to full lineage records.

    Reasoning Plane sees only handles (REF_xxx).
    Audit Plane stores the complete lineage chain.

    Production backend: Neo4j (graph DB) + append-only S3.
    This implementation: in-memory registry (same interface).
    """

    def __init__(self) -> None:
        self._records: dict[str, LineageRecord] = {}
        self._counter = 0
        self._decision_refs: dict[str, list[str]] = {}  # decision_id → [ref_ids]

    def register(
        self,
        source_type: str,
        source_doc_id: str | None = None,
        ingestion_batch: str | None = None,
        transformation_job: str | None = None,
        embedding_model_version: str | None = None,
        chunk_id: str | None = None,
        confidence: float | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> ProvenanceHandle:
        """Register a data source and return a lightweight reference handle.

        The handle is safe to inject into the Reasoning Plane.
        The full lineage record stays in the Audit Plane.
        """
        self._counter += 1
        ref_id = f"REF_{self._counter:04d}"

        record = LineageRecord(
            ref_id=ref_id,
            source_doc_id=source_doc_id,
            ingestion_batch=ingestion_batch,
            transformation_job=transformation_job,
            embedding_model_version=embedding_model_version,
            chunk_id=chunk_id,
            confidence=confidence,
            metadata=metadata or {},
        )
        self._records[ref_id] = record

        return ProvenanceHandle(ref_id=ref_id, source_type=source_type)

    def resolve(self, ref_id: str) -> LineageRecord | None:
        """Resolve a reference handle to its full lineage record."""
        return self._records.get(ref_id)

    def link_to_decision(self, decision_id: str, ref_ids: list[str]) -> None:
        """Link provenance handles to a decision for backward tracing."""
        self._decision_refs[decision_id] = ref_ids

    def trace_forward(self, source_doc_id: str) -> list[LineageRecord]:
        """Forward lineage: source_doc → all downstream records."""
        return [r for r in self._records.values() if r.source_doc_id == source_doc_id]

    def trace_backward(self, decision_id: str) -> list[LineageRecord]:
        """Backward lineage: decision → all contributing sources."""
        ref_ids = self._decision_refs.get(decision_id, [])
        return [self._records[rid] for rid in ref_ids if rid in self._records]

    def completeness_check(self) -> dict[str, Any]:
        """Verify provenance completeness. Returns stats and gaps.

        Provenance completeness must be 100% to pass deployment gate.
        """
        total = len(self._records)
        complete = sum(
            1 for r in self._records.values()
            if r.source_doc_id and r.chunk_id
        )
        missing_source = [r.ref_id for r in self._records.values() if not r.source_doc_id]
        missing_chunk = [r.ref_id for r in self._records.values() if not r.chunk_id]

        return {
            "total_records": total,
            "complete": complete,
            "completeness_pct": round(complete / total * 100, 2) if total > 0 else 100.0,
            "missing_source_doc": missing_source,
            "missing_chunk_id": missing_chunk,
            "deployment_gate": complete == total,
        }

    @property
    def handle_count(self) -> int:
        return len(self._records)

    def estimate_token_savings(self) -> dict[str, int]:
        """Compare token cost: reference handles vs inline metadata."""
        inline_per_chunk = 80  # Typical inline provenance (source, timestamp, confidence, etc.)
        handle_per_chunk = 2   # REF_xxx
        n = len(self._records)
        return {
            "inline_tokens": inline_per_chunk * n,
            "handle_tokens": handle_per_chunk * n,
            "tokens_saved": (inline_per_chunk - handle_per_chunk) * n,
            "overhead_pct": round(handle_per_chunk / inline_per_chunk * 100, 1) if inline_per_chunk > 0 else 0,
        }
