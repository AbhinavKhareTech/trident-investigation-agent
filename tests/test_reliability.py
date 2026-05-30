"""Tests for reliability package — retrieval SRE, SLOs, latency."""

from __future__ import annotations

import time
from trident_engine.reliability.retrieval_sre import RetrievalSRE, AlertSeverity
from trident_engine.reliability.slos import SLOTracker, SLOStatus
from trident_engine.reliability.latency import LatencyBudget


class TestRetrievalSRE:
    def test_healthy_metric(self):
        sre = RetrievalSRE()
        alert = sre.record("precision_at_5", 0.85)
        assert alert is None  # Above target

    def test_alerting_metric(self):
        sre = RetrievalSRE()
        alert = sre.record("precision_at_5", 0.65)
        assert alert is not None
        assert alert.severity == AlertSeverity.WARNING

    def test_health_check(self):
        sre = RetrievalSRE()
        sre.record("precision_at_5", 0.85)
        sre.record("grounding_accuracy", 0.95)
        health = sre.health_check()
        assert health["metrics"]["precision_at_5"]["healthy"] is True


class TestSLOTracker:
    def test_healthy_slo(self):
        tracker = SLOTracker()
        breach = tracker.record("workflow_success_rate", 0.998)
        assert breach is None

    def test_breached_slo(self):
        tracker = SLOTracker()
        breach = tracker.record("workflow_success_rate", 0.980)
        assert breach is not None
        assert breach.slo_name == "workflow_success_rate"

    def test_dashboard(self):
        tracker = SLOTracker()
        tracker.record("workflow_success_rate", 0.998)
        tracker.record("hallucination_rate", 0.002)
        dash = tracker.dashboard()
        assert dash["slos"]["workflow_success_rate"]["status"] == "healthy"


class TestLatencyBudget:
    def test_phase_tracking(self):
        budget = LatencyBudget()
        budget.start_phase("intent_ccs")
        time.sleep(0.01)  # 10ms
        m = budget.end_phase("intent_ccs")
        assert m.elapsed_ms > 0
        assert m.phase == "intent_ccs"

    def test_sla_check(self):
        budget = LatencyBudget()
        # Simulate fast phases
        for phase in ["intent_ccs", "retrieval_rerank", "dedup_compression", "assembly_handles", "llm_ttft"]:
            budget.start_phase(phase)
            budget.end_phase(phase)
        sla = budget.check_sla()
        assert sla["within_sla"] is True  # Near-instant in test

    def test_summary(self):
        budget = LatencyBudget()
        summary = budget.summary()
        assert summary["sla_ms"] == 2000.0
        assert "intent_ccs" in summary["phases"]

    def test_remaining_budget(self):
        budget = LatencyBudget()
        budget.start_phase("intent_ccs")
        budget.end_phase("intent_ccs")
        remaining = budget.remaining_budget_ms()
        assert remaining >= 0
        assert remaining <= 2000.0
