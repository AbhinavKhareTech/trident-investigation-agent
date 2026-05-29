"""Graph builder: CSV → heterogeneous investigation graph.

Builds a NetworkX graph from tabular data. Each CSV row becomes
nodes + edges. Implicit relationships (shared phone, shared address,
shared provider) are discovered and linked automatically.

Production: this would feed into PyG/DGL for GNN inference.
Demo: NetworkX + community detection is sufficient and CPU-friendly.
"""

from __future__ import annotations

import csv
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

import networkx as nx

from demo.investigation_agent.models import AgentEvent, Entity, InvestigationPhase, Relationship, Severity, generate_id

logger = logging.getLogger(__name__)


class InvestigationGraph:
    """Heterogeneous graph for investigation with typed nodes and edges."""

    def __init__(self) -> None:
        self.G = nx.Graph()
        self._entities: dict[str, Entity] = {}
        self._relationships: list[Relationship] = []
        self._events: list[AgentEvent] = []

        # Indexes for implicit relationship discovery
        self._phone_index: dict[str, list[str]] = defaultdict(list)
        self._address_index: dict[str, list[str]] = defaultdict(list)
        self._provider_index: dict[str, list[str]] = defaultdict(list)

    @property
    def node_count(self) -> int:
        return self.G.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.G.number_of_edges()

    @property
    def events(self) -> list[AgentEvent]:
        return self._events

    def get_entity(self, entity_id: str) -> Entity | None:
        return self._entities.get(entity_id)

    def get_neighbors(self, entity_id: str) -> list[Entity]:
        if entity_id not in self.G:
            return []
        return [self._entities[n] for n in self.G.neighbors(entity_id) if n in self._entities]

    def ingest_customers(self, filepath: str) -> int:
        """Ingest customers.csv → person nodes."""
        count = 0
        with open(filepath) as f:
            for row in csv.DictReader(f):
                entity = Entity(
                    id=row["customer_id"],
                    entity_type="person",
                    name=row["name"],
                    properties={
                        "phone": row.get("phone", ""),
                        "email": row.get("email", ""),
                        "city": row.get("city", ""),
                        "area": row.get("area", ""),
                        "address": row.get("address", ""),
                        "risk_tier": row.get("risk_tier", "unknown"),
                    },
                )
                self._add_entity(entity)

                # Index for implicit relationship discovery
                phone = row.get("phone", "").strip()
                if phone:
                    self._phone_index[phone].append(entity.id)
                address = row.get("address", "").strip()
                if address:
                    self._address_index[address].append(entity.id)

                count += 1

        self._emit("ingest", f"Ingested {count} customers", {"count": count, "type": "customers"})
        return count

    def ingest_claims(self, filepath: str) -> int:
        """Ingest claims.csv → claim nodes + edges to customers, providers."""
        count = 0
        with open(filepath) as f:
            for row in csv.DictReader(f):
                # Claim node
                claim = Entity(
                    id=row["claim_id"],
                    entity_type="claim",
                    name=f"Claim {row['claim_id']}",
                    properties={
                        "date": row.get("date", ""),
                        "vehicle": row.get("vehicle", ""),
                        "damage": row.get("damage", ""),
                        "description": row.get("description", ""),
                        "repair_amount": float(row.get("repair_amount", 0)),
                        "medical_amount": float(row.get("medical_amount", 0)),
                        "total_amount": float(row.get("total_amount", 0)),
                        "status": row.get("status", ""),
                        "city": row.get("city", ""),
                    },
                )
                self._add_entity(claim)

                # Edge: claim → customer
                customer_id = row.get("customer_id", "")
                if customer_id:
                    self._add_relationship(customer_id, claim.id, "filed_claim")

                # Garage node + edge
                garage = row.get("garage", "").strip()
                if garage:
                    garage_id = f"GAR_{garage.replace(' ', '_')}"
                    if garage_id not in self._entities:
                        self._add_entity(Entity(
                            id=garage_id, entity_type="provider",
                            name=garage, properties={"provider_type": "garage"},
                        ))
                    self._add_relationship(claim.id, garage_id, "repaired_at")
                    self._provider_index[garage_id].append(customer_id)

                # Hospital node + edge
                hospital = row.get("hospital", "").strip()
                if hospital:
                    hosp_id = f"HOS_{hospital.replace(' ', '_')}"
                    if hosp_id not in self._entities:
                        self._add_entity(Entity(
                            id=hosp_id, entity_type="provider",
                            name=hospital, properties={"provider_type": "hospital"},
                        ))
                    self._add_relationship(claim.id, hosp_id, "treated_at")
                    self._provider_index[hosp_id].append(customer_id)

                # Agent edge
                agent_id = row.get("agent_id", "").strip()
                if agent_id and agent_id in self._entities:
                    self._add_relationship(claim.id, agent_id, "handled_by")

                count += 1

        self._emit("ingest", f"Ingested {count} claims", {"count": count, "type": "claims"})
        return count

    def ingest_payments(self, filepath: str) -> int:
        """Ingest payments.csv → payment edges."""
        count = 0
        with open(filepath) as f:
            for row in csv.DictReader(f):
                pay = Entity(
                    id=row["payment_id"],
                    entity_type="payment",
                    name=f"Payment {row['payment_id']}",
                    properties={
                        "amount": float(row.get("amount", 0)),
                        "date": row.get("date", ""),
                        "payee": row.get("payee", ""),
                        "method": row.get("method", ""),
                    },
                )
                self._add_entity(pay)

                claim_id = row.get("claim_id", "")
                if claim_id:
                    self._add_relationship(claim_id, pay.id, "paid_via")

                customer_id = row.get("customer_id", "")
                if customer_id:
                    self._add_relationship(pay.id, customer_id, "paid_to")

                count += 1

        self._emit("ingest", f"Ingested {count} payments", {"count": count, "type": "payments"})
        return count

    def ingest_agents(self, filepath: str) -> int:
        """Ingest agents.csv → agent nodes."""
        count = 0
        with open(filepath) as f:
            for row in csv.DictReader(f):
                entity = Entity(
                    id=row["agent_id"],
                    entity_type="agent",
                    name=row.get("name", row["agent_id"]),
                    properties={
                        "region": row.get("region", ""),
                        "cases_handled": int(row.get("cases_handled", 0)),
                    },
                )
                self._add_entity(entity)
                count += 1

        self._emit("ingest", f"Ingested {count} agents", {"count": count, "type": "agents"})
        return count

    def discover_implicit_relationships(self) -> int:
        """Discover hidden connections: shared phones, addresses, providers.

        This is where the magic happens. Explicit data (CSVs) becomes
        implicit graph structure that reveals fraud rings.
        """
        discovered = 0

        # Shared phone numbers
        for phone, entity_ids in self._phone_index.items():
            if len(entity_ids) > 1:
                for i, eid1 in enumerate(entity_ids):
                    for eid2 in entity_ids[i + 1:]:
                        self._add_relationship(eid1, eid2, "shares_phone", {"phone": phone})
                        discovered += 1

        # Shared addresses
        for address, entity_ids in self._address_index.items():
            if len(entity_ids) > 1:
                for i, eid1 in enumerate(entity_ids):
                    for eid2 in entity_ids[i + 1:]:
                        self._add_relationship(eid1, eid2, "shares_address", {"address": address})
                        discovered += 1

        # Provider clusters (many customers using same provider in short time)
        for provider_id, customer_ids in self._provider_index.items():
            unique = list(set(customer_ids))
            if len(unique) >= 4:  # Threshold: 4+ customers same provider
                for i, cid1 in enumerate(unique):
                    for cid2 in unique[i + 1:]:
                        if not self.G.has_edge(cid1, cid2):
                            self._add_relationship(cid1, cid2, "same_provider", {"provider": provider_id})
                            discovered += 1

        self._emit(
            "edge_added",
            f"Discovered {discovered} implicit relationships",
            {"count": discovered, "types": ["shares_phone", "shares_address", "same_provider"]},
            severity=Severity.MEDIUM,
        )
        return discovered

    def get_subgraph(self, entity_ids: list[str], depth: int = 1) -> nx.Graph:
        """Extract a subgraph around given entities up to depth hops."""
        nodes = set(entity_ids)
        for _ in range(depth):
            frontier = set()
            for n in nodes:
                if n in self.G:
                    frontier.update(self.G.neighbors(n))
            nodes.update(frontier)
        return self.G.subgraph(nodes).copy()

    def to_serializable(self) -> dict[str, Any]:
        """Serialize graph for JSON/WebSocket transmission."""
        nodes = []
        for nid, data in self.G.nodes(data=True):
            entity = self._entities.get(nid)
            if entity:
                nodes.append({
                    "id": nid,
                    "type": entity.entity_type,
                    "name": entity.name,
                    "risk_score": entity.risk_score,
                    "flagged": entity.flagged,
                })

        edges = []
        for u, v, data in self.G.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "type": data.get("rel_type", "related"),
                "weight": data.get("weight", 1.0),
            })

        return {"nodes": nodes, "edges": edges}

    # ─── Internal ───

    def _add_entity(self, entity: Entity) -> None:
        self._entities[entity.id] = entity
        self.G.add_node(entity.id, entity_type=entity.entity_type, name=entity.name)

    def _add_relationship(self, source: str, target: str, rel_type: str, props: dict | None = None) -> None:
        if source not in self.G or target not in self.G:
            return
        self.G.add_edge(source, target, rel_type=rel_type, weight=1.0, **(props or {}))
        self._relationships.append(Relationship(
            id=generate_id("rel"), source_id=source, target_id=target,
            rel_type=rel_type, properties=props or {},
        ))

    def _emit(self, event_type: str, message: str, data: dict | None = None, severity: Severity = Severity.LOW) -> None:
        self._events.append(AgentEvent(
            event_type=event_type,
            phase=InvestigationPhase.OBSERVE,
            message=message,
            data=data or {},
            severity=severity,
        ))
