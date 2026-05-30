"""Three-plane context architecture.

Reasoning plane: optimized LLM cognition (volatile, in-memory).
Execution plane: workflow/FSM state (ephemeral, stateful).
Audit plane: compliance, lineage, HITL (immutable, persistent).

Critical constraint: audit metadata NEVER enters the Reasoning plane.
Only reference handles (REF_xxx) are permitted to cross the boundary.

Playbook v8.0 Parts 5, 13.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class PlaneType(str, Enum):
    REASONING = "reasoning"
    EXECUTION = "execution"
    AUDIT = "audit"


@dataclass
class ContextBlock:
    """A single block in the context assembly pipeline."""

    block_id: str
    block_type: str  # persona, task, rag, graph_signal, history, constraints, safety
    content: str
    token_count: int
    source: str  # YAML path, RAG chunk ID, etc.
    provenance_ref: str | None = None  # REF_xxx handle
    is_static: bool = False
    is_critical: bool = False  # Never compress or degrade
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReasoningPlane:
    """Optimized for LLM cognition. Volatile, in-memory.

    Contains: persona, task instruction, top-K RAG, structured graph signals,
    compressed history, constraints, output schema.

    Max tokens governed by per-agent token budget.
    Audit metadata is excluded — only reference handles permitted.
    """

    agent_id: str
    max_tokens: int
    blocks: list[ContextBlock] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return sum(b.token_count for b in self.blocks)

    @property
    def remaining_tokens(self) -> int:
        return self.max_tokens - self.total_tokens

    @property
    def utilization(self) -> float:
        return self.total_tokens / self.max_tokens if self.max_tokens > 0 else 0.0

    def add_block(self, block: ContextBlock) -> bool:
        """Add a block if it fits within budget. Returns False if rejected."""
        if block.token_count > self.remaining_tokens:
            return False
        self.blocks.append(block)
        return True

    def assemble(self) -> str:
        """Assemble all blocks into final prompt string.

        Ordering: static prefix blocks first, dynamic middle, static suffix last.
        Safety constraints placed at primacy (start) and recency (end) positions.
        """
        prefix = [b for b in self.blocks if b.is_static and b.block_type in ("persona", "rules", "constraints")]
        middle = [b for b in self.blocks if not b.is_static or b.block_type not in ("persona", "rules", "constraints", "schema")]
        suffix = [b for b in self.blocks if b.is_static and b.block_type == "schema"]

        ordered = prefix + middle + suffix
        return "\n\n".join(b.content for b in ordered)

    def validate_no_audit_leak(self) -> list[str]:
        """Verify no audit-plane metadata has leaked into reasoning context.

        Returns list of violations (empty = clean).
        """
        violations = []
        audit_markers = ["lineage_graph", "full_provenance", "reviewer_id", "audit_trail"]
        for block in self.blocks:
            for marker in audit_markers:
                if marker in block.content.lower():
                    violations.append(f"Block {block.block_id}: audit marker '{marker}' found in reasoning plane")
        return violations


@dataclass
class ExecutionPlane:
    """Workflow and tool execution state. Ephemeral, stateful.

    Contains: FSM state, tool schemas, parameter bindings, retry metadata.
    Deterministic — LLM output is validated against allowed transitions.
    """

    session_id: str
    fsm_state: str = "IDLE"
    tool_bindings: dict[str, Any] = field(default_factory=dict)
    retry_counts: dict[str, int] = field(default_factory=dict)
    max_retries: int = 3

    def record_tool_call(self, tool_name: str, params: dict[str, Any], result: Any) -> None:
        self.tool_bindings[tool_name] = {
            "params": params,
            "result": result,
            "timestamp": time.time(),
        }

    def increment_retry(self, tool_name: str) -> bool:
        """Increment retry count. Returns False if max retries exceeded."""
        count = self.retry_counts.get(tool_name, 0) + 1
        self.retry_counts[tool_name] = count
        return count <= self.max_retries


@dataclass
class AuditRecord:
    """Single immutable audit record."""

    record_id: str
    timestamp: float
    record_type: str  # inference, human_decision, escalation, transition
    payload: dict[str, Any]
    context_hash: str  # SHA-256 of the reasoning plane at time of record

    def __post_init__(self) -> None:
        if not self.timestamp:
            self.timestamp = time.time()


class AuditPlane:
    """Compliance, lineage, HITL records. Immutable, persistent.

    Contains: full provenance chain, decision rationale, confidence intervals,
    escalation triggers, reviewer decisions.

    Storage: append-only. Records are never modified or deleted.
    Retention: 7 years for BFSI (MiFID II, SR 11-7).
    """

    def __init__(self) -> None:
        self._records: list[AuditRecord] = []

    @property
    def record_count(self) -> int:
        return len(self._records)

    def log_inference(
        self,
        context_hash: str,
        model_version: str,
        business_rules_version: str,
        output_hash: str,
        provenance_refs: list[str],
    ) -> AuditRecord:
        """Log an inference event with full provenance."""
        record = AuditRecord(
            record_id=self._generate_id("inf"),
            timestamp=time.time(),
            record_type="inference",
            payload={
                "model_version": model_version,
                "business_rules_version": business_rules_version,
                "output_hash": output_hash,
                "provenance_refs": provenance_refs,
            },
            context_hash=context_hash,
        )
        self._records.append(record)
        return record

    def log_human_decision(
        self,
        context_hash: str,
        escalation_trigger: str,
        reviewer_id: str,
        decision: str,
        rationale: str,
    ) -> AuditRecord:
        """Log a human-in-the-loop decision."""
        record = AuditRecord(
            record_id=self._generate_id("hitl"),
            timestamp=time.time(),
            record_type="human_decision",
            payload={
                "escalation_trigger": escalation_trigger,
                "reviewer_id": reviewer_id,
                "decision": decision,
                "rationale": rationale,
            },
            context_hash=context_hash,
        )
        self._records.append(record)
        return record

    def log_transition(
        self,
        context_hash: str,
        from_state: str,
        to_state: str,
        trigger: str,
    ) -> AuditRecord:
        """Log an FSM state transition."""
        record = AuditRecord(
            record_id=self._generate_id("fsm"),
            timestamp=time.time(),
            record_type="transition",
            payload={
                "from_state": from_state,
                "to_state": to_state,
                "trigger": trigger,
            },
            context_hash=context_hash,
        )
        self._records.append(record)
        return record

    def query_by_type(self, record_type: str) -> list[AuditRecord]:
        return [r for r in self._records if r.record_type == record_type]

    def query_by_ref(self, provenance_ref: str) -> list[AuditRecord]:
        """Backward lineage: find all records referencing a provenance handle."""
        return [
            r for r in self._records
            if provenance_ref in r.payload.get("provenance_refs", [])
        ]

    @staticmethod
    def hash_context(content: str) -> str:
        return hashlib.sha256(content.encode()).hexdigest()

    def _generate_id(self, prefix: str) -> str:
        return f"{prefix}_{int(time.time() * 1000)}_{len(self._records)}"
