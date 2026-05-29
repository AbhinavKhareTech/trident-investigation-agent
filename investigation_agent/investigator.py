"""Investigation engine: hypothesis generation + evidence collection.

Takes anomalies from the detector and builds an investigation:
1. Generate hypotheses from anomaly patterns
2. Gather supporting/contradicting evidence from graph
3. Assess confidence
4. Recommend actions
"""

from __future__ import annotations

import logging
from typing import Any

from demo.investigation_agent.models import (
    Anomaly, CaseFile, Hypothesis, Severity, generate_id,
)
from demo.investigation_agent.graph_builder import InvestigationGraph

logger = logging.getLogger(__name__)


class Investigator:
    """Autonomous investigation engine."""

    # Hypothesis templates by anomaly type
    HYPOTHESIS_TEMPLATES = {
        "suspicious_cluster": {
            "title": "Coordinated Fraud Ring",
            "template": (
                "A group of {cluster_size} entities appear to be operating as a coordinated ring. "
                "They share {shared_phones} phone numbers, {shared_addresses} addresses, "
                "and route claims through {common_providers} common provider(s). "
                "Total claims value: ₹{total_amount:,.0f}."
            ),
        },
        "shared_identity": {
            "title": "Identity Manipulation",
            "template": (
                "Multiple entities share {signal} identifiers, suggesting possible identity "
                "manipulation or synthetic identity creation."
            ),
        },
        "amount_outlier": {
            "title": "Claim Amount Inflation",
            "template": (
                "Claim amount of ₹{amount:,.0f} deviates {zscore:.1f} standard deviations "
                "from the mean (₹{mean:,.0f}), suggesting possible inflation."
            ),
        },
        "provider_concentration": {
            "title": "Provider Collusion",
            "template": (
                "Provider is linked to {claim_count} claims totaling ₹{total_amount:,.0f}. "
                "This concentration exceeds expected patterns and may indicate kickback "
                "arrangements or inflated billing."
            ),
        },
        "temporal_burst": {
            "title": "Staged Incident Pattern",
            "template": (
                "{claim_count} claims filed on {date} suggest a possible staged incident "
                "or coordinated filing pattern."
            ),
        },
    }

    def investigate(
        self,
        anomalies: list[Anomaly],
        graph: InvestigationGraph,
    ) -> CaseFile:
        """Run full investigation and produce a case file."""

        # Group anomalies by severity
        critical = [a for a in anomalies if a.severity in (Severity.CRITICAL, Severity.HIGH)]
        if not critical:
            critical = anomalies[:3]  # Take top 3 even if medium

        # Generate hypotheses
        hypotheses = []
        all_entity_ids: set[str] = set()

        for anomaly in critical:
            hypothesis = self._generate_hypothesis(anomaly, graph)
            if hypothesis:
                hypotheses.append(hypothesis)
                all_entity_ids.update(anomaly.entity_ids)

        # Cross-reference: do different anomalies point at the same entities?
        convergence = self._check_convergence(critical)

        # Build case file
        overall_severity = Severity.CRITICAL if any(
            a.severity == Severity.CRITICAL for a in critical
        ) else Severity.HIGH

        overall_confidence = max((h.confidence for h in hypotheses), default=0.0)

        actions = self._recommend_actions(hypotheses, convergence, overall_confidence)

        # Build investigation timeline
        timeline = self._build_timeline(anomalies, graph)

        # Compute total exposure
        total_exposure = sum(
            a.evidence.get("total_amount", 0) for a in critical
        )

        case = CaseFile(
            case_id=generate_id("CASE"),
            title=self._generate_case_title(hypotheses, convergence),
            severity=overall_severity,
            summary=self._generate_summary(hypotheses, convergence, total_exposure),
            hypotheses=hypotheses,
            anomalies=critical,
            entity_ids=list(all_entity_ids),
            recommended_actions=actions,
            timeline=timeline,
            confidence=overall_confidence,
        )

        return case

    def _generate_hypothesis(self, anomaly: Anomaly, graph: InvestigationGraph) -> Hypothesis | None:
        """Generate a hypothesis from an anomaly."""
        template_info = self.HYPOTHESIS_TEMPLATES.get(anomaly.anomaly_type)
        if not template_info:
            return None

        # Build description from template
        try:
            description = template_info["template"].format(**anomaly.evidence)
        except (KeyError, ValueError):
            description = anomaly.description

        # Gather supporting evidence
        supporting = self._gather_supporting_evidence(anomaly, graph)
        contradicting = self._gather_contradicting_evidence(anomaly, graph)

        # Compute confidence based on evidence balance
        support_weight = sum(e.get("weight", 1.0) for e in supporting)
        contradict_weight = sum(e.get("weight", 1.0) for e in contradicting)
        total_weight = support_weight + contradict_weight
        confidence = support_weight / total_weight if total_weight > 0 else 0.5

        return Hypothesis(
            id=generate_id("HYP"),
            title=template_info["title"],
            description=description,
            anomaly_ids=[anomaly.id],
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            confidence=round(confidence, 3),
            status="supported" if confidence > 0.6 else "inconclusive",
        )

    def _gather_supporting_evidence(self, anomaly: Anomaly, graph: InvestigationGraph) -> list[dict[str, Any]]:
        """Gather evidence that supports the anomaly hypothesis."""
        evidence = []

        if anomaly.anomaly_type == "suspicious_cluster":
            # Check centrality of key nodes
            subG = graph.get_subgraph(anomaly.entity_ids)
            if subG.number_of_nodes() > 0:
                centrality = dict(sorted(
                    nx_betweenness(subG).items(), key=lambda x: x[1], reverse=True,
                )[:3])
                for nid, score in centrality.items():
                    entity = graph.get_entity(nid)
                    if entity and score > 0.1:
                        evidence.append({
                            "type": "centrality",
                            "description": f"{entity.name} ({entity.entity_type}) is a central connector (betweenness: {score:.3f})",
                            "entity_id": nid,
                            "weight": score * 3,
                        })

        # Amount evidence
        for eid in anomaly.entity_ids:
            entity = graph.get_entity(eid)
            if entity and entity.entity_type == "claim":
                amt = entity.properties.get("total_amount", 0)
                if amt > 100000:
                    evidence.append({
                        "type": "high_amount",
                        "description": f"High claim value: ₹{amt:,.0f}",
                        "entity_id": eid,
                        "weight": 1.5,
                    })

        # Provider evidence
        providers_seen: set[str] = set()
        for eid in anomaly.entity_ids:
            for neighbor in graph.G.neighbors(eid) if eid in graph.G else []:
                n_entity = graph.get_entity(neighbor)
                if n_entity and n_entity.entity_type == "provider" and neighbor not in providers_seen:
                    providers_seen.add(neighbor)
                    claim_count = sum(
                        1 for e in graph.G.neighbors(neighbor)
                        if graph.get_entity(e) and graph.get_entity(e).entity_type == "claim"
                    )
                    if claim_count >= 4:
                        evidence.append({
                            "type": "provider_concentration",
                            "description": f"Provider '{n_entity.name}' linked to {claim_count} claims in this network",
                            "entity_id": neighbor,
                            "weight": 2.0,
                        })

        return evidence

    def _gather_contradicting_evidence(self, anomaly: Anomaly, graph: InvestigationGraph) -> list[dict[str, Any]]:
        """Gather evidence that contradicts the hypothesis."""
        evidence = []

        # Check if entities have long legitimate history
        for eid in anomaly.entity_ids[:5]:
            entity = graph.get_entity(eid)
            if entity and entity.properties.get("risk_tier") == "low":
                evidence.append({
                    "type": "low_risk_history",
                    "description": f"{entity.name} has a low historical risk tier",
                    "entity_id": eid,
                    "weight": 0.5,
                })

        return evidence

    def _check_convergence(self, anomalies: list[Anomaly]) -> dict[str, Any]:
        """Check if multiple anomalies point to the same entities."""
        entity_counts: dict[str, int] = {}
        for a in anomalies:
            for eid in a.entity_ids:
                entity_counts[eid] = entity_counts.get(eid, 0) + 1

        converging = {eid: count for eid, count in entity_counts.items() if count >= 2}
        return {
            "converging_entities": len(converging),
            "max_convergence": max(converging.values()) if converging else 0,
            "entity_ids": list(converging.keys()),
        }

    def _recommend_actions(
        self, hypotheses: list[Hypothesis], convergence: dict, confidence: float,
    ) -> list[str]:
        """Generate recommended actions based on investigation results."""
        actions = []

        if confidence > 0.8:
            actions.append("IMMEDIATE: Refer to Special Investigation Unit (SIU)")
            actions.append("FREEZE: Suspend all pending payouts for linked claims")
        elif confidence > 0.6:
            actions.append("ESCALATE: Flag for senior analyst review within 24h")
            actions.append("HOLD: Place 48h hold on pending payouts")
        else:
            actions.append("MONITOR: Add entities to watchlist for 90 days")

        if convergence["converging_entities"] > 0:
            actions.append(
                f"INVESTIGATE: {convergence['converging_entities']} entities appear in multiple anomalies — "
                "cross-reference with external databases"
            )

        # Provider-specific actions
        for h in hypotheses:
            if h.title == "Provider Collusion" and h.confidence > 0.6:
                actions.append("AUDIT: Schedule on-site audit of flagged provider")

        actions.append("DOCUMENT: Full audit trail preserved (case file generated)")
        return actions

    def _generate_case_title(self, hypotheses: list[Hypothesis], convergence: dict) -> str:
        if any(h.title == "Coordinated Fraud Ring" for h in hypotheses):
            return "Suspected Coordinated Fraud Ring"
        if any(h.title == "Provider Collusion" for h in hypotheses):
            return "Provider Collusion Investigation"
        return "Anomaly Investigation"

    def _generate_summary(self, hypotheses: list[Hypothesis], convergence: dict, total_exposure: float) -> str:
        n_hyp = len(hypotheses)
        supported = sum(1 for h in hypotheses if h.status == "supported")
        return (
            f"Investigation identified {n_hyp} hypothesis(es), {supported} supported by evidence. "
            f"Total exposure: ₹{total_exposure:,.0f}. "
            f"{convergence['converging_entities']} entities appear across multiple signals. "
            f"Highest confidence: {max((h.confidence for h in hypotheses), default=0):.0%}."
        )

    def _build_timeline(self, anomalies: list[Anomaly], graph: InvestigationGraph) -> list[dict[str, Any]]:
        """Build an investigation timeline from anomaly data."""
        events = []
        for a in anomalies:
            events.append({
                "timestamp": a.detected_at,
                "event": f"Anomaly detected: {a.anomaly_type}",
                "severity": a.severity.value,
                "description": a.description[:100],
            })
        events.sort(key=lambda e: e["timestamp"])
        return events


def nx_betweenness(G: "nx.Graph") -> dict:
    """Safe betweenness centrality."""
    import networkx as nx
    try:
        return nx.betweenness_centrality(G)
    except Exception:
        return {}
