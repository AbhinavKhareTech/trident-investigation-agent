"""Tests for lineage package — graph, inference log, handles."""

from __future__ import annotations

from trident_engine.lineage.graph import LineageGraph, LineageNode, LineageEdge
from trident_engine.lineage.inference_log import InferenceLog
from trident_engine.lineage.handles import HandleGenerator


class TestLineageGraph:
    def test_register_full_chain(self):
        graph = LineageGraph()
        chunk_id = graph.register_full_chain(
            source_doc_id="doc_001",
            ingestion_batch="batch_2026_05",
            transform_job="transform_v2",
            embedding_model="bge-large-v1.5",
            chunk_id="chunk_042",
        )
        assert chunk_id == "chunk_042"

    def test_forward_trace(self):
        graph = LineageGraph()
        graph.register_full_chain("doc_A", "batch_1", "tf_1", "emb_1", "c1")
        graph.register_full_chain("doc_A", "batch_1", "tf_1", "emb_1", "c2")
        forward = graph.trace_forward("doc_A")
        assert len(forward) >= 2  # At least batch + downstream

    def test_backward_trace(self):
        graph = LineageGraph()
        graph.register_full_chain("doc_A", "batch_1", "tf_1", "emb_1", "c1")
        graph.link_chunk_to_decision("c1", "decision_001", confidence=0.87)
        backward = graph.trace_backward("decision_001")
        assert any(n.node_id == "c1" for n in backward)

    def test_impact_analysis(self):
        graph = LineageGraph()
        graph.register_full_chain("doc_X", "b1", "t1", "e1", "c1")
        graph.register_full_chain("doc_X", "b1", "t1", "e1", "c2")
        graph.link_chunk_to_decision("c1", "dec_1")
        graph.link_chunk_to_decision("c2", "dec_2")
        impact = graph.impact_analysis("doc_X")
        assert impact["impacted_decisions"] == 2

    def test_completeness_report(self):
        graph = LineageGraph()
        graph.register_full_chain("doc_A", "b1", "t1", "e1", "c1")
        graph.link_chunk_to_decision("c1", "dec_1")
        report = graph.completeness_report()
        assert report["deployment_gate"] is True


class TestInferenceLog:
    def test_append_immutable(self):
        log = InferenceLog()
        record = log.append(
            session_id="s1",
            agent_id="supervisor",
            context_hash="abc123",
            model_version="frontier-v1",
            business_rules_version="rules_v3",
            output_hash="def456",
            provenance_refs=["REF_001", "REF_002"],
        )
        assert record.record_id == "inf_000001"
        assert log.total_records == 1

    def test_query_by_session(self):
        log = InferenceLog()
        log.append("s1", "a1", "h1", "m1", "r1", "o1", [])
        log.append("s1", "a2", "h2", "m1", "r1", "o2", [])
        log.append("s2", "a1", "h3", "m1", "r1", "o3", [])
        results = log.query_by_session("s1")
        assert len(results) == 2

    def test_query_by_provenance(self):
        log = InferenceLog()
        log.append("s1", "a1", "h1", "m1", "r1", "o1", ["REF_001", "REF_002"])
        log.append("s1", "a2", "h2", "m1", "r1", "o2", ["REF_003"])
        results = log.query_by_provenance("REF_001")
        assert len(results) == 1

    def test_integrity_check(self):
        log = InferenceLog()
        log.append("s1", "a1", "h1", "m1", "r1", "o1", [])
        log.append("s1", "a2", "h2", "m1", "r1", "o2", [])
        result = log.verify_integrity()
        assert result["integrity_ok"] is True


class TestHandleGenerator:
    def test_sequential_generation(self):
        gen = HandleGenerator(mode="sequential")
        h1 = gen.generate()
        h2 = gen.generate()
        assert h1 == "REF_0001"
        assert h2 == "REF_0002"

    def test_content_addressed(self):
        gen = HandleGenerator(mode="content")
        h1 = gen.generate(content="some document content")
        h2 = gen.generate(content="some document content")
        # Same content should produce different handles (already issued)
        assert h1 != h2  # Collision handled

    def test_is_valid(self):
        gen = HandleGenerator()
        h = gen.generate()
        assert gen.is_valid(h) is True
        assert gen.is_valid("REF_9999") is False
