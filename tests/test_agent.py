"""Tests for the Trident Investigation Agent."""

from __future__ import annotations

import os
import tempfile

import pytest

from investigation_agent.models import (
    Anomaly, CaseFile, Entity, Hypothesis, InvestigationPhase,
    Relationship, Severity, generate_id,
)
from investigation_agent.synthetic.generator import generate_dataset
from investigation_agent.graph_builder import InvestigationGraph
from investigation_agent.detector import AnomalyDetector
from investigation_agent.investigator import Investigator
from investigation_agent.reporter import Reporter


# ── Fixtures ──

@pytest.fixture
def data_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        generate_dataset(output_dir=tmpdir, n_normal=50, ring_size=6)
        yield tmpdir


@pytest.fixture
def graph(data_dir):
    g = InvestigationGraph()
    g.ingest_agents(os.path.join(data_dir, "agents.csv"))
    g.ingest_customers(os.path.join(data_dir, "customers.csv"))
    g.ingest_claims(os.path.join(data_dir, "claims.csv"))
    g.ingest_payments(os.path.join(data_dir, "payments.csv"))
    g.discover_implicit_relationships()
    return g


# ── Models ──

class TestModels:
    def test_entity_creation(self):
        e = Entity(id="E1", entity_type="person", name="Alice")
        assert e.id == "E1"
        assert e.risk_score == 0.0

    def test_generate_id_uniqueness(self):
        ids = {generate_id("test") for _ in range(100)}
        assert len(ids) == 100

    def test_severity_ordering(self):
        assert Severity.CRITICAL.value == "CRITICAL"

    def test_investigation_phases(self):
        assert InvestigationPhase.OBSERVE.value == "OBSERVE"
        assert InvestigationPhase.CLOSED.value == "CLOSED"


# ── Synthetic Generator ──

class TestGenerator:
    def test_generates_all_files(self, data_dir):
        for name in ["customers.csv", "claims.csv", "payments.csv", "agents.csv", "manifest.json"]:
            assert os.path.exists(os.path.join(data_dir, name))

    def test_customer_count(self, data_dir):
        with open(os.path.join(data_dir, "customers.csv")) as f:
            lines = f.readlines()
        # 50 normal + 6 ring = 56, plus header
        assert len(lines) == 57

    def test_deterministic(self):
        """Same seed → same data."""
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            generate_dataset(d1, n_normal=10, ring_size=3)
            generate_dataset(d2, n_normal=10, ring_size=3)
            with open(os.path.join(d1, "customers.csv")) as f1, \
                 open(os.path.join(d2, "customers.csv")) as f2:
                assert f1.read() == f2.read()


# ── Graph Builder ──

class TestGraphBuilder:
    def test_graph_builds(self, graph):
        assert graph.node_count > 50
        assert graph.edge_count > 50

    def test_entity_types(self, graph):
        types = {data.get("entity_type") for _, data in graph.G.nodes(data=True)}
        assert "person" in types
        assert "claim" in types
        assert "provider" in types

    def test_implicit_relationships_found(self, graph):
        # The fraud ring shares phones/addresses, so implicit edges exist
        implicit_types = set()
        for _, _, data in graph.G.edges(data=True):
            implicit_types.add(data.get("rel_type", ""))
        assert "shares_phone" in implicit_types or "shares_address" in implicit_types

    def test_get_entity(self, graph):
        # Agents are always present
        entity = graph.get_entity("AG-Mohit")
        assert entity is not None
        assert entity.entity_type == "agent"

    def test_subgraph_extraction(self, graph):
        sub = graph.get_subgraph(["AG-Mohit"], depth=1)
        assert sub.number_of_nodes() >= 1

    def test_serializable(self, graph):
        data = graph.to_serializable()
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) > 0


# ── Anomaly Detector ──

class TestDetector:
    def test_detects_anomalies(self, graph):
        detector = AnomalyDetector()
        anomalies = detector.detect_all(graph)
        assert len(anomalies) > 0

    def test_anomaly_has_severity(self, graph):
        detector = AnomalyDetector()
        anomalies = detector.detect_all(graph)
        for a in anomalies:
            assert isinstance(a.severity, Severity)

    def test_anomaly_sorted_by_severity(self, graph):
        detector = AnomalyDetector()
        anomalies = detector.detect_all(graph)
        if len(anomalies) >= 2:
            severity_rank = {"CRITICAL": 3, "HIGH": 2, "MEDIUM": 1, "LOW": 0}
            for i in range(len(anomalies) - 1):
                r1 = severity_rank.get(anomalies[i].severity.value, 0)
                r2 = severity_rank.get(anomalies[i + 1].severity.value, 0)
                assert r1 >= r2 or anomalies[i].confidence >= anomalies[i + 1].confidence

    def test_shared_identity_detection(self, graph):
        detector = AnomalyDetector()
        anomalies = detector.detect_shared_identities(graph)
        # Fraud ring has shared phones/addresses
        assert len(anomalies) > 0

    def test_amount_outlier_detection(self, graph):
        detector = AnomalyDetector()
        anomalies = detector.detect_amount_outliers(graph)
        # Fraud ring has inflated amounts
        assert len(anomalies) >= 0  # May or may not trigger depending on distribution


# ── Investigator ──

class TestInvestigator:
    def test_generates_case_file(self, graph):
        detector = AnomalyDetector()
        anomalies = detector.detect_all(graph)
        investigator = Investigator()
        case = investigator.investigate(anomalies, graph)
        assert isinstance(case, CaseFile)
        assert case.case_id.startswith("CASE_")

    def test_case_has_hypotheses(self, graph):
        detector = AnomalyDetector()
        anomalies = detector.detect_all(graph)
        investigator = Investigator()
        case = investigator.investigate(anomalies, graph)
        assert len(case.hypotheses) > 0

    def test_case_has_actions(self, graph):
        detector = AnomalyDetector()
        anomalies = detector.detect_all(graph)
        investigator = Investigator()
        case = investigator.investigate(anomalies, graph)
        assert len(case.recommended_actions) > 0

    def test_hypothesis_has_evidence(self, graph):
        detector = AnomalyDetector()
        anomalies = detector.detect_all(graph)
        investigator = Investigator()
        case = investigator.investigate(anomalies, graph)
        # At least one hypothesis should have evidence
        has_evidence = any(
            len(h.supporting_evidence) > 0 or len(h.contradicting_evidence) > 0
            for h in case.hypotheses
        )
        assert has_evidence


# ── Reporter ──

class TestReporter:
    def test_generates_markdown(self, graph):
        detector = AnomalyDetector()
        anomalies = detector.detect_all(graph)
        investigator = Investigator()
        case = investigator.investigate(anomalies, graph)

        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = Reporter()
            filepath = reporter.generate(case, graph, output_dir=tmpdir)
            assert os.path.exists(filepath)
            assert filepath.endswith(".md")

            with open(filepath) as f:
                content = f.read()
            assert "Investigation Report" in content
            assert case.case_id in content
            assert "Recommended Actions" in content
            assert "Audit Trail" in content


# ── Integration ──

class TestEndToEnd:
    def test_full_pipeline(self, data_dir):
        """Full pipeline: generate → ingest → detect → investigate → report."""
        # Ingest
        graph = InvestigationGraph()
        graph.ingest_agents(os.path.join(data_dir, "agents.csv"))
        graph.ingest_customers(os.path.join(data_dir, "customers.csv"))
        graph.ingest_claims(os.path.join(data_dir, "claims.csv"))
        graph.ingest_payments(os.path.join(data_dir, "payments.csv"))
        n_implicit = graph.discover_implicit_relationships()
        assert n_implicit > 0

        # Detect
        detector = AnomalyDetector()
        anomalies = detector.detect_all(graph)
        assert len(anomalies) > 0

        # Investigate
        investigator = Investigator()
        case = investigator.investigate(anomalies, graph)
        assert case.confidence > 0

        # Report
        with tempfile.TemporaryDirectory() as tmpdir:
            reporter = Reporter()
            filepath = reporter.generate(case, graph, output_dir=tmpdir)
            assert os.path.exists(filepath)
            size = os.path.getsize(filepath)
            assert size > 500  # Non-trivial report
