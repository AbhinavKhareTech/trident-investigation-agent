"""Lineage graph operations.

Provides forward and backward provenance tracing across the full data lifecycle:
source_doc → ingestion_batch → transform_job → embedding_model → chunk → decision

Production backend: Neo4j with 7-year retention (BFSI: MiFID II, SR 11-7).
This implementation: in-memory adjacency list (same query interface).

Playbook v8.0 Part 26.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class LineageNode:
    """A node in the lineage graph."""

    node_id: str
    node_type: str  # source_doc, ingestion_batch, transform_job, embedding_model, chunk, decision
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.time()


@dataclass
class LineageEdge:
    """A directed edge in the lineage graph."""

    from_id: str
    to_id: str
    edge_type: str  # produced_by, transformed_by, embedded_by, chunked_from, used_in
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = time.time()


class LineageGraph:
    """In-memory lineage graph with Neo4j-compatible query patterns.

    Query patterns:
    - Forward: source_doc_id → all downstream decisions
    - Backward: decision_id → all contributing sources + confidence
    - Impact: which decisions would be affected if source_doc X is retracted?
    """

    def __init__(self) -> None:
        self._nodes: dict[str, LineageNode] = {}
        self._edges: list[LineageEdge] = []
        self._forward: dict[str, list[str]] = {}   # node_id → [downstream_ids]
        self._backward: dict[str, list[str]] = {}   # node_id → [upstream_ids]

    def add_node(self, node: LineageNode) -> None:
        self._nodes[node.node_id] = node

    def add_edge(self, edge: LineageEdge) -> None:
        if edge.from_id not in self._nodes or edge.to_id not in self._nodes:
            raise ValueError(
                f"Both nodes must exist: {edge.from_id}, {edge.to_id}"
            )
        self._edges.append(edge)
        self._forward.setdefault(edge.from_id, []).append(edge.to_id)
        self._backward.setdefault(edge.to_id, []).append(edge.from_id)

    def trace_forward(self, node_id: str, max_depth: int = 10) -> list[LineageNode]:
        """Forward lineage: find all downstream nodes from a source."""
        visited: set[str] = set()
        result: list[LineageNode] = []
        self._dfs_forward(node_id, visited, result, 0, max_depth)
        return result

    def trace_backward(self, node_id: str, max_depth: int = 10) -> list[LineageNode]:
        """Backward lineage: find all upstream sources for a decision."""
        visited: set[str] = set()
        result: list[LineageNode] = []
        self._dfs_backward(node_id, visited, result, 0, max_depth)
        return result

    def impact_analysis(self, source_doc_id: str) -> dict[str, Any]:
        """If a source document is retracted, which decisions are impacted?"""
        downstream = self.trace_forward(source_doc_id)
        decisions = [n for n in downstream if n.node_type == "decision"]
        chunks = [n for n in downstream if n.node_type == "chunk"]
        return {
            "source_doc_id": source_doc_id,
            "impacted_decisions": len(decisions),
            "impacted_chunks": len(chunks),
            "decision_ids": [d.node_id for d in decisions],
            "chunk_ids": [c.node_id for c in chunks],
        }

    def register_full_chain(
        self,
        source_doc_id: str,
        ingestion_batch: str,
        transform_job: str,
        embedding_model: str,
        chunk_id: str,
        properties: dict[str, Any] | None = None,
    ) -> str:
        """Register a complete lineage chain from source to chunk.

        Returns the chunk_id for downstream linking.
        """
        props = properties or {}

        nodes = [
            LineageNode(source_doc_id, "source_doc", props),
            LineageNode(ingestion_batch, "ingestion_batch"),
            LineageNode(transform_job, "transform_job"),
            LineageNode(embedding_model, "embedding_model"),
            LineageNode(chunk_id, "chunk", props),
        ]
        for node in nodes:
            if node.node_id not in self._nodes:
                self.add_node(node)

        edges = [
            LineageEdge(source_doc_id, ingestion_batch, "ingested_by"),
            LineageEdge(ingestion_batch, transform_job, "transformed_by"),
            LineageEdge(transform_job, embedding_model, "embedded_by"),
            LineageEdge(embedding_model, chunk_id, "chunked_into"),
        ]
        for edge in edges:
            self.add_edge(edge)

        return chunk_id

    def link_chunk_to_decision(self, chunk_id: str, decision_id: str, confidence: float = 0.0) -> None:
        """Link a chunk to a decision (forward: chunk → decision)."""
        if decision_id not in self._nodes:
            self.add_node(LineageNode(decision_id, "decision", {"confidence": confidence}))
        self.add_edge(LineageEdge(chunk_id, decision_id, "used_in", {"confidence": confidence}))

    def completeness_report(self) -> dict[str, Any]:
        """Check lineage completeness across all nodes."""
        chunks = [n for n in self._nodes.values() if n.node_type == "chunk"]
        chunks_with_source = sum(
            1 for c in chunks if self.trace_backward(c.node_id)
        )
        decisions = [n for n in self._nodes.values() if n.node_type == "decision"]
        decisions_with_lineage = sum(
            1 for d in decisions
            if any(n.node_type == "source_doc" for n in self.trace_backward(d.node_id))
        )

        total_chunks = len(chunks)
        total_decisions = len(decisions)

        return {
            "total_nodes": len(self._nodes),
            "total_edges": len(self._edges),
            "chunks": total_chunks,
            "chunks_with_source": chunks_with_source,
            "chunk_completeness_pct": round(chunks_with_source / total_chunks * 100, 2) if total_chunks else 100.0,
            "decisions": total_decisions,
            "decisions_with_lineage": decisions_with_lineage,
            "decision_completeness_pct": round(decisions_with_lineage / total_decisions * 100, 2) if total_decisions else 100.0,
            "deployment_gate": chunks_with_source == total_chunks and decisions_with_lineage == total_decisions,
        }

    def _dfs_forward(self, node_id: str, visited: set[str], result: list[LineageNode], depth: int, max_depth: int) -> None:
        if depth > max_depth or node_id in visited:
            return
        visited.add(node_id)
        if node_id in self._nodes and depth > 0:
            result.append(self._nodes[node_id])
        for child in self._forward.get(node_id, []):
            self._dfs_forward(child, visited, result, depth + 1, max_depth)

    def _dfs_backward(self, node_id: str, visited: set[str], result: list[LineageNode], depth: int, max_depth: int) -> None:
        if depth > max_depth or node_id in visited:
            return
        visited.add(node_id)
        if node_id in self._nodes and depth > 0:
            result.append(self._nodes[node_id])
        for parent in self._backward.get(node_id, []):
            self._dfs_backward(parent, visited, result, depth + 1, max_depth)
