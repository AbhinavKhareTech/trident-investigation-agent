"""Domain-agnostic data models for the investigation agent.

Everything is an Entity with typed Relationships.
Domain packs (insurance, AML, vendor) just define new entity/edge types.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class Severity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class InvestigationPhase(str, Enum):
    OBSERVE = "OBSERVE"
    DETECT = "DETECT"
    HYPOTHESIZE = "HYPOTHESIZE"
    INVESTIGATE = "INVESTIGATE"
    COLLECT_EVIDENCE = "COLLECT_EVIDENCE"
    ASSESS_CONFIDENCE = "ASSESS_CONFIDENCE"
    RECOMMEND_ACTION = "RECOMMEND_ACTION"
    CREATE_AUDIT_TRAIL = "CREATE_AUDIT_TRAIL"
    CLOSED = "CLOSED"


@dataclass
class Entity:
    """A node in the investigation graph."""

    id: str
    entity_type: str  # person, organization, account, claim, device, location, ...
    name: str
    properties: dict[str, Any] = field(default_factory=dict)
    risk_score: float = 0.0
    flagged: bool = False
    created_at: float = field(default_factory=time.time)

    def __hash__(self) -> int:
        return hash(self.id)


@dataclass
class Relationship:
    """An edge in the investigation graph."""

    id: str
    source_id: str
    target_id: str
    rel_type: str  # filed_by, paid_to, shares_phone, shares_address, ...
    properties: dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0
    created_at: float = field(default_factory=time.time)


@dataclass
class Anomaly:
    """A detected anomaly in the graph."""

    id: str
    anomaly_type: str  # cluster, velocity, outlier, shared_identity, cycle
    severity: Severity
    description: str
    entity_ids: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    confidence: float = 0.0
    detected_at: float = field(default_factory=time.time)


@dataclass
class Hypothesis:
    """An investigative hypothesis generated from anomalies."""

    id: str
    title: str
    description: str
    anomaly_ids: list[str] = field(default_factory=list)
    supporting_evidence: list[dict[str, Any]] = field(default_factory=list)
    contradicting_evidence: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    status: str = "pending"  # pending, supported, refuted, inconclusive


@dataclass
class CaseFile:
    """The final investigation output."""

    case_id: str
    title: str
    severity: Severity
    summary: str
    hypotheses: list[Hypothesis] = field(default_factory=list)
    anomalies: list[Anomaly] = field(default_factory=list)
    entity_ids: list[str] = field(default_factory=list)
    recommended_actions: list[str] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0
    created_at: float = field(default_factory=time.time)


@dataclass
class AgentEvent:
    """An event emitted by the agent for live visualization."""

    event_type: str  # ingest, node_added, edge_added, anomaly_detected, phase_change, case_created
    phase: InvestigationPhase
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)
    severity: Severity = Severity.LOW


def generate_id(prefix: str = "") -> str:
    short = uuid.uuid4().hex[:8]
    return f"{prefix}_{short}" if prefix else short
