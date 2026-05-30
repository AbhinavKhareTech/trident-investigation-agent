"""Tests for context engineering package.

Covers: three-plane separation, token budgets, cognitive entropy,
loss-aware compression, graph signal abstraction, provenance handles,
and JIT context assembly.
"""

from __future__ import annotations

import pytest

from trident_engine.context.planes import (
    AuditPlane,
    ContextBlock,
    ExecutionPlane,
    ReasoningPlane,
)
from trident_engine.context.budgets import (
    BudgetState,
    CategoryBudget,
    DegradationAction,
    TokenBudget,
    TokenBudgetEnforcer,
)
from trident_engine.context.entropy import (
    CognitiveEntropyMonitor,
    EntropyAction,
    EntropyMetrics,
)
from trident_engine.context.compressor import (
    CRITICAL_FIELDS,
    CriticalFieldSet,
    LossAwareCompressor,
)
from trident_engine.context.signals import DecisionSignal, GraphSignalAbstractor
from trident_engine.context.provenance import ProvenanceHandle, ProvenanceRegistry


# ── Reasoning Plane ──

class TestReasoningPlane:
    def test_add_block_within_budget(self):
        plane = ReasoningPlane(agent_id="test", max_tokens=1000)
        block = ContextBlock("b1", "persona", "Hello", 50, "test.yaml", is_static=True)
        assert plane.add_block(block) is True
        assert plane.total_tokens == 50
        assert plane.remaining_tokens == 950

    def test_add_block_over_budget(self):
        plane = ReasoningPlane(agent_id="test", max_tokens=100)
        block = ContextBlock("b1", "persona", "x" * 500, 200, "test.yaml")
        assert plane.add_block(block) is False
        assert plane.total_tokens == 0

    def test_validate_no_audit_leak_clean(self):
        plane = ReasoningPlane(agent_id="test", max_tokens=1000)
        plane.add_block(ContextBlock("b1", "persona", "You are a helpful assistant", 10, "test"))
        assert plane.validate_no_audit_leak() == []

    def test_validate_no_audit_leak_detected(self):
        plane = ReasoningPlane(agent_id="test", max_tokens=1000)
        plane.add_block(ContextBlock("b1", "rag", "Full audit_trail data here", 10, "test"))
        violations = plane.validate_no_audit_leak()
        assert len(violations) == 1

    def test_assemble_ordering(self):
        plane = ReasoningPlane(agent_id="test", max_tokens=5000)
        plane.add_block(ContextBlock("b1", "rag", "RAG content", 10, "rag", is_static=False))
        plane.add_block(ContextBlock("b2", "persona", "Persona", 10, "persona", is_static=True))
        plane.add_block(ContextBlock("b3", "schema", "Schema", 10, "schema", is_static=True))
        assembled = plane.assemble()
        # Persona (static prefix) should come before RAG (dynamic middle)
        assert assembled.index("Persona") < assembled.index("RAG")
        assert assembled.index("RAG") < assembled.index("Schema")


# ── Execution Plane ──

class TestExecutionPlane:
    def test_record_tool_call(self):
        plane = ExecutionPlane(session_id="s1")
        plane.record_tool_call("search_restaurants", {"query": "biryani"}, {"found": 5})
        assert "search_restaurants" in plane.tool_bindings

    def test_retry_tracking(self):
        plane = ExecutionPlane(session_id="s1", max_retries=2)
        assert plane.increment_retry("tool_a") is True   # 1
        assert plane.increment_retry("tool_a") is True   # 2
        assert plane.increment_retry("tool_a") is False   # 3 > max


# ── Audit Plane ──

class TestAuditPlane:
    def test_log_inference(self):
        audit = AuditPlane()
        record = audit.log_inference("hash123", "frontier-v1", "rules_v3", "out_hash", ["REF_001"])
        assert record.record_type == "inference"
        assert audit.record_count == 1

    def test_log_human_decision(self):
        audit = AuditPlane()
        record = audit.log_human_decision("hash", "high_entropy", "reviewer_42", "approved", "looks correct")
        assert record.record_type == "human_decision"

    def test_query_by_ref(self):
        audit = AuditPlane()
        audit.log_inference("h1", "m1", "r1", "o1", ["REF_001", "REF_002"])
        audit.log_inference("h2", "m1", "r1", "o2", ["REF_003"])
        results = audit.query_by_ref("REF_001")
        assert len(results) == 1


# ── Token Budget ──

class TestTokenBudget:
    def test_budget_creation(self):
        budget = TokenBudget(
            agent_id="supervisor",
            model_tier="frontier",
            hard_cap=4000,
            categories=[
                CategoryBudget("persona", 20.0, True, [], never_degrade=True),
                CategoryBudget("rag", 35.0, False, [DegradationAction.REDUCE_K]),
                CategoryBudget("signals", 15.0, False, [DegradationAction.LOSSY_TOP3]),
                CategoryBudget("history", 15.0, False, [DegradationAction.REDUCE_WINDOW]),
                CategoryBudget("task", 10.0, True, [DegradationAction.DROP_FEWSHOT]),
                CategoryBudget("entropy", 5.0, False, []),
            ],
        )
        assert budget.tokens_for("persona") == 800
        assert budget.tokens_for("rag") == 1400

    def test_budget_rejects_bad_percentages(self):
        with pytest.raises(ValueError, match="must be ~100%"):
            TokenBudget(
                agent_id="bad",
                model_tier="frontier",
                hard_cap=4000,
                categories=[
                    CategoryBudget("a", 50.0, True, []),
                    CategoryBudget("b", 60.0, True, []),  # sums to 110%
                ],
            )


class TestBudgetState:
    def _make_budget(self) -> TokenBudget:
        return TokenBudget(
            agent_id="test",
            model_tier="strong",
            hard_cap=1000,
            categories=[
                CategoryBudget("rag", 50.0, False, []),
                CategoryBudget("other", 50.0, False, []),
            ],
        )

    def test_try_allocate_success(self):
        state = BudgetState(budget=self._make_budget())
        assert state.try_allocate("rag", 400) is True
        assert state.total_used == 400

    def test_try_allocate_over_category(self):
        state = BudgetState(budget=self._make_budget())
        assert state.try_allocate("rag", 600) is False  # 600 > 500 (50% of 1000)


class TestTokenBudgetEnforcer:
    def test_session_tracking(self):
        enforcer = TokenBudgetEnforcer()
        budget = TokenBudget("sup", "frontier", 4000, [
            CategoryBudget("rag", 100.0, False, []),
        ])
        enforcer.register_agent(budget)
        state = enforcer.start_invocation("sup")
        state.try_allocate("rag", 2000)
        assert enforcer.session_tokens_used == 2000


# ── Cognitive Entropy ──

class TestCognitiveEntropy:
    def test_ccs_computation(self):
        metrics = EntropyMetrics(
            contradiction_density=0.0,
            ambiguity_score=0.0,
            temporal_consistency=1.0,
            cross_agent_conflict=0.0,
        )
        assert metrics.ccs == 0.0  # Perfect context

    def test_ccs_high_contradiction(self):
        metrics = EntropyMetrics(contradiction_density=1.0)
        assert metrics.ccs >= 0.35  # Contradiction dominates

    def test_autonomous_threshold(self):
        monitor = CognitiveEntropyMonitor()
        metrics = EntropyMetrics(contradiction_density=0.1)
        snapshot = monitor.evaluate("s1", "a1", metrics)
        assert snapshot.action_taken == EntropyAction.AUTONOMOUS

    def test_hitl_threshold(self):
        monitor = CognitiveEntropyMonitor()
        metrics = EntropyMetrics(
            contradiction_density=0.8,
            cross_agent_conflict=0.8,
            ambiguity_score=0.6,
        )
        snapshot = monitor.evaluate("s1", "a1", metrics)
        assert snapshot.action_taken in (EntropyAction.PARTITION_HITL, EntropyAction.FREEZE_KILLSWITCH)

    def test_ensemble_conflict_detection(self):
        monitor = CognitiveEntropyMonitor()
        variance, is_conflict = monitor.check_ensemble_conflict(0.95, 0.1, 0.1)
        assert is_conflict is True  # Large spread


# ── Loss-Aware Compressor ──

class TestLossAwareCompressor:
    def test_critical_field_extraction(self):
        data = {
            "order_id": "ORD_123",
            "amount": 549.00,
            "items": [{"name": "Biryani", "price": 299}],
            "notes": "Extra spicy",
        }
        critical = CriticalFieldSet.extract(data)
        assert "order_id" in str(critical.fields)
        assert "amount" in str(critical.fields)
        assert critical.verify() is True

    def test_compression_preserves_critical(self):
        compressor = LossAwareCompressor(target_ratio=0.5)
        content = "The user ordered biryani from Meghana's. " * 20
        metadata = {"order_id": "ORD_123", "amount": 549.00}
        result = compressor.compress(content, metadata)
        assert result.integrity_verified is True
        assert "ORD_123" in result.compressed_content or result.critical_fields.fields.get("order_id") == "ORD_123"

    def test_history_compression(self):
        compressor = LossAwareCompressor()
        turns = [
            {"role": "user", "content": "Order biryani from Meghana's for dinner tonight " * 5},
            {"role": "assistant", "content": "Found 3 restaurants near Koramangala with biryani " * 5},
            {"role": "user", "content": "Pick Meghana's Foods, add chicken biryani and raita " * 3},
            {"role": "assistant", "content": "Added to cart. Chicken Biryani Rs 349, Raita Rs 99. Total Rs 549. " * 3},
            {"role": "user", "content": "Confirm the order please"},
        ]
        result = compressor.compress_history(turns, target_tokens=100, max_turns=2)
        assert result.integrity_verified is True


# ── Graph Signal Abstractor ──

class TestGraphSignalAbstractor:
    def test_abstract_ensemble_result(self):
        abstractor = GraphSignalAbstractor()
        result = abstractor.abstract({
            "ensemble_score": 0.85,
            "pyg_structural": 0.95,
            "dgl_temporal": 0.10,
            "xgb_tabular": 0.10,
        })
        assert isinstance(result, DecisionSignal)
        assert result.disagreement_flag is True  # Large spread
        assert result.intent_divergence == "high"

    def test_context_block_token_count(self):
        abstractor = GraphSignalAbstractor()
        result = abstractor.abstract({
            "ensemble_score": 0.85,
            "pyg_structural": 0.80,
            "dgl_temporal": 0.82,
            "xgb_tabular": 0.78,
        })
        block = result.to_context_block()
        # Should be roughly 120 tokens (~480 chars)
        assert len(block) < 600

    def test_should_escalate(self):
        abstractor = GraphSignalAbstractor()
        signal = abstractor.abstract({
            "ensemble_score": 0.3,
            "pyg_structural": 0.9,
            "dgl_temporal": 0.1,
            "xgb_tabular": 0.2,
        })
        assert abstractor.should_escalate(signal) is True

    def test_token_savings(self):
        savings = GraphSignalAbstractor.estimate_token_savings(10)
        assert savings["reduction_pct"] == 85.0


# ── Provenance Registry ──

class TestProvenanceRegistry:
    def test_register_and_resolve(self):
        registry = ProvenanceRegistry()
        handle = registry.register(
            source_type="rag_chunk",
            source_doc_id="doc_001",
            chunk_id="chunk_042",
            confidence=0.87,
        )
        assert handle.ref_id == "REF_0001"
        record = registry.resolve("REF_0001")
        assert record is not None
        assert record.source_doc_id == "doc_001"

    def test_forward_trace(self):
        registry = ProvenanceRegistry()
        registry.register(source_type="rag", source_doc_id="doc_A", chunk_id="c1")
        registry.register(source_type="rag", source_doc_id="doc_A", chunk_id="c2")
        registry.register(source_type="rag", source_doc_id="doc_B", chunk_id="c3")
        forward = registry.trace_forward("doc_A")
        assert len(forward) == 2

    def test_completeness_check(self):
        registry = ProvenanceRegistry()
        registry.register(source_type="rag", source_doc_id="doc_A", chunk_id="c1")
        registry.register(source_type="rag", source_doc_id=None, chunk_id="c2")  # Missing source
        report = registry.completeness_check()
        assert report["completeness_pct"] == 50.0
        assert report["deployment_gate"] is False

    def test_token_savings_estimate(self):
        registry = ProvenanceRegistry()
        for i in range(10):
            registry.register(source_type="rag", source_doc_id=f"d{i}", chunk_id=f"c{i}")
        savings = registry.estimate_token_savings()
        assert savings["handle_tokens"] == 20
        assert savings["inline_tokens"] == 800
