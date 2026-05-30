"""Anomaly detection on the investigation graph.

Detects:
1. Suspicious clusters (community detection + scoring)
2. Temporal velocity spikes (burst patterns)
3. Shared identity signals (phone, address, device)
4. Amount outliers (statistical deviation)
5. Provider concentration (many claims → one provider)

All CPU-friendly. No GPU required.
"""

from __future__ import annotations

import logging
import statistics
from collections import Counter, defaultdict
from typing import Any

import networkx as nx
from networkx.algorithms import community as nx_community

from investigation_agent.models import AgentEvent, Anomaly, InvestigationPhase, Severity, generate_id
from investigation_agent.graph_builder import InvestigationGraph

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Multi-signal anomaly detector for investigation graphs."""

    def __init__(
        self,
        cluster_min_size: int = 3,
        velocity_threshold: int = 4,
        amount_zscore_threshold: float = 2.0,
        provider_concentration_threshold: int = 4,
    ) -> None:
        self.cluster_min_size = cluster_min_size
        self.velocity_threshold = velocity_threshold
        self.amount_zscore_threshold = amount_zscore_threshold
        self.provider_concentration_threshold = provider_concentration_threshold

    def detect_all(self, graph: InvestigationGraph) -> list[Anomaly]:
        """Run all detection algorithms. Returns anomalies sorted by severity."""
        anomalies: list[Anomaly] = []

        anomalies.extend(self.detect_suspicious_clusters(graph))
        anomalies.extend(self.detect_shared_identities(graph))
        anomalies.extend(self.detect_amount_outliers(graph))
        anomalies.extend(self.detect_provider_concentration(graph))
        anomalies.extend(self.detect_temporal_bursts(graph))

        # Score and sort
        for a in anomalies:
            a.confidence = self._compute_confidence(a, graph)

        anomalies.sort(key=lambda a: (-self._severity_rank(a.severity), -a.confidence))
        return anomalies

    def detect_suspicious_clusters(self, graph: InvestigationGraph) -> list[Anomaly]:
        """Community detection → suspicious cluster identification."""
        if graph.node_count < 3:
            return []

        anomalies = []

        # Extract person-to-person subgraph (shared identities)
        person_nodes = [
            nid for nid, data in graph.G.nodes(data=True)
            if data.get("entity_type") == "person"
        ]
        if len(person_nodes) < 3:
            return []

        # Build subgraph of persons connected by implicit relationships
        person_edges = [
            (u, v) for u, v, d in graph.G.edges(data=True)
            if d.get("rel_type") in ("shares_phone", "shares_address", "same_provider")
            and u in person_nodes and v in person_nodes
        ]

        if not person_edges:
            return []

        subG = nx.Graph()
        subG.add_nodes_from(person_nodes)
        subG.add_edges_from(person_edges)

        # Community detection (Louvain-like via greedy modularity)
        try:
            communities = list(nx_community.greedy_modularity_communities(subG))
        except Exception:
            communities = list(nx.connected_components(subG))

        for i, comm in enumerate(communities):
            if len(comm) < self.cluster_min_size:
                continue

            entity_ids = list(comm)

            # Score the cluster
            signals = self._score_cluster(entity_ids, graph)
            if signals["risk_score"] < 0.5:
                continue

            severity = Severity.CRITICAL if signals["risk_score"] > 0.8 else Severity.HIGH

            anomalies.append(Anomaly(
                id=generate_id("ANM"),
                anomaly_type="suspicious_cluster",
                severity=severity,
                description=(
                    f"Ring #{i + 1}: {len(entity_ids)} connected entities. "
                    f"Shared phones: {signals['shared_phones']}, "
                    f"shared addresses: {signals['shared_addresses']}, "
                    f"common providers: {signals['common_providers']}. "
                    f"Total claims value: ₹{signals['total_amount']:,.0f}."
                ),
                entity_ids=entity_ids,
                evidence=signals,
                confidence=signals["risk_score"],
            ))

        return anomalies

    def detect_shared_identities(self, graph: InvestigationGraph) -> list[Anomaly]:
        """Find entities sharing phone numbers, addresses, or devices."""
        anomalies = []

        # Check for shared-identity edges
        shared_phone_groups: dict[str, list[str]] = defaultdict(list)
        shared_addr_groups: dict[str, list[str]] = defaultdict(list)

        for u, v, data in graph.G.edges(data=True):
            rel = data.get("rel_type", "")
            if rel == "shares_phone":
                key = data.get("phone", "unknown")
                shared_phone_groups[key].extend([u, v])
            elif rel == "shares_address":
                key = data.get("address", "unknown")
                shared_addr_groups[key].extend([u, v])

        for phone, entities in shared_phone_groups.items():
            unique = list(set(entities))
            if len(unique) >= 2:
                anomalies.append(Anomaly(
                    id=generate_id("ANM"),
                    anomaly_type="shared_identity",
                    severity=Severity.HIGH if len(unique) >= 3 else Severity.MEDIUM,
                    description=f"{len(unique)} entities share phone {phone[-4:]}****",
                    entity_ids=unique,
                    evidence={"signal": "shared_phone", "phone_suffix": phone[-4:]},
                    confidence=min(1.0, len(unique) * 0.3),
                ))

        for address, entities in shared_addr_groups.items():
            unique = list(set(entities))
            if len(unique) >= 3:
                anomalies.append(Anomaly(
                    id=generate_id("ANM"),
                    anomaly_type="shared_identity",
                    severity=Severity.HIGH,
                    description=f"{len(unique)} entities share address: {address[:40]}...",
                    entity_ids=unique,
                    evidence={"signal": "shared_address", "address": address},
                    confidence=min(1.0, len(unique) * 0.25),
                ))

        return anomalies

    def detect_amount_outliers(self, graph: InvestigationGraph) -> list[Anomaly]:
        """Statistical outlier detection on claim amounts."""
        anomalies = []

        amounts = []
        claim_data: list[tuple[str, float]] = []

        for nid, entity in graph._entities.items():
            if entity.entity_type == "claim":
                amt = entity.properties.get("total_amount", 0)
                if amt > 0:
                    amounts.append(amt)
                    claim_data.append((nid, amt))

        if len(amounts) < 10:
            return []

        mean = statistics.mean(amounts)
        stdev = statistics.stdev(amounts)
        if stdev == 0:
            return []

        for claim_id, amt in claim_data:
            zscore = (amt - mean) / stdev
            if zscore > self.amount_zscore_threshold:
                entity = graph.get_entity(claim_id)
                anomalies.append(Anomaly(
                    id=generate_id("ANM"),
                    anomaly_type="amount_outlier",
                    severity=Severity.MEDIUM if zscore < 3 else Severity.HIGH,
                    description=f"Claim {claim_id}: ₹{amt:,.0f} is {zscore:.1f}σ above mean (₹{mean:,.0f})",
                    entity_ids=[claim_id],
                    evidence={"amount": amt, "mean": mean, "stdev": stdev, "zscore": zscore},
                    confidence=min(1.0, zscore * 0.25),
                ))

        return anomalies

    def detect_provider_concentration(self, graph: InvestigationGraph) -> list[Anomaly]:
        """Detect providers with unusually high claim concentration."""
        anomalies = []

        provider_claims: dict[str, list[str]] = defaultdict(list)
        for u, v, data in graph.G.edges(data=True):
            if data.get("rel_type") in ("repaired_at", "treated_at"):
                claim_id = u
                provider_id = v
                provider_claims[provider_id].append(claim_id)

        for provider_id, claims in provider_claims.items():
            if len(claims) >= self.provider_concentration_threshold:
                entity = graph.get_entity(provider_id)
                total = sum(
                    graph._entities[c].properties.get("total_amount", 0)
                    for c in claims if c in graph._entities
                )
                anomalies.append(Anomaly(
                    id=generate_id("ANM"),
                    anomaly_type="provider_concentration",
                    severity=Severity.HIGH if len(claims) >= 6 else Severity.MEDIUM,
                    description=(
                        f"Provider '{entity.name if entity else provider_id}' "
                        f"linked to {len(claims)} claims totaling ₹{total:,.0f}"
                    ),
                    entity_ids=[provider_id] + claims,
                    evidence={"provider": provider_id, "claim_count": len(claims), "total_amount": total},
                    confidence=min(1.0, len(claims) * 0.15),
                ))

        return anomalies

    def detect_temporal_bursts(self, graph: InvestigationGraph) -> list[Anomaly]:
        """Detect temporal clustering of claims (burst patterns)."""
        anomalies = []

        # Group claims by date
        date_claims: dict[str, list[str]] = defaultdict(list)
        for nid, entity in graph._entities.items():
            if entity.entity_type == "claim":
                date = entity.properties.get("date", "")
                if date:
                    date_claims[date].append(nid)

        # Check for burst days
        for date, claims in date_claims.items():
            if len(claims) >= self.velocity_threshold:
                total = sum(
                    graph._entities[c].properties.get("total_amount", 0)
                    for c in claims
                )
                anomalies.append(Anomaly(
                    id=generate_id("ANM"),
                    anomaly_type="temporal_burst",
                    severity=Severity.MEDIUM,
                    description=f"{len(claims)} claims on {date} totaling ₹{total:,.0f}",
                    entity_ids=claims,
                    evidence={"date": date, "claim_count": len(claims), "total_amount": total},
                    confidence=min(1.0, len(claims) * 0.2),
                ))

        return anomalies

    # ─── Scoring ───

    def _score_cluster(self, entity_ids: list[str], graph: InvestigationGraph) -> dict[str, Any]:
        """Score a cluster of entities for suspiciousness."""
        shared_phones = 0
        shared_addresses = 0
        common_providers: set[str] = set()
        total_amount = 0.0

        for eid in entity_ids:
            for neighbor in graph.G.neighbors(eid):
                edge_data = graph.G.edges[eid, neighbor]
                rel = edge_data.get("rel_type", "")
                if rel == "shares_phone":
                    shared_phones += 1
                elif rel == "shares_address":
                    shared_addresses += 1

                # Check claims for this entity
                n_entity = graph.get_entity(neighbor)
                if n_entity and n_entity.entity_type == "claim":
                    total_amount += n_entity.properties.get("total_amount", 0)
                elif n_entity and n_entity.entity_type == "provider":
                    common_providers.add(neighbor)

        # Risk score: weighted combination of signals
        score = min(1.0, (
            0.3 * min(1.0, shared_phones / 3)
            + 0.3 * min(1.0, shared_addresses / 2)
            + 0.2 * min(1.0, len(common_providers) / 3)
            + 0.2 * min(1.0, len(entity_ids) / 6)
        ))

        return {
            "shared_phones": shared_phones,
            "shared_addresses": shared_addresses,
            "common_providers": len(common_providers),
            "total_amount": total_amount,
            "cluster_size": len(entity_ids),
            "risk_score": round(score, 3),
        }

    @staticmethod
    def _severity_rank(s: Severity) -> int:
        return {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}.get(s.value, 0)

    @staticmethod
    def _compute_confidence(anomaly: Anomaly, graph: InvestigationGraph) -> float:
        """Refine confidence based on multi-signal convergence."""
        base = anomaly.confidence
        # Boost if multiple signal types converge on same entities
        if anomaly.anomaly_type == "suspicious_cluster":
            evidence = anomaly.evidence
            signals = sum([
                1 if evidence.get("shared_phones", 0) > 0 else 0,
                1 if evidence.get("shared_addresses", 0) > 0 else 0,
                1 if evidence.get("common_providers", 0) > 0 else 0,
            ])
            base = min(1.0, base + signals * 0.1)
        return round(base, 3)
