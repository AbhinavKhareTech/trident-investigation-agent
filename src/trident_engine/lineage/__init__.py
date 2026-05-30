"""Provenance & Audit infrastructure.

Forward lineage: source_doc → all downstream decisions
Backward lineage: decision → all contributing sources + confidence

Storage: Neo4j (graph DB) + append-only S3 (inference log)
This package provides the in-memory reference implementation.

Playbook v8.0 Part 26.
"""

from trident_engine.lineage.graph import LineageGraph
from trident_engine.lineage.inference_log import InferenceLog
from trident_engine.lineage.handles import HandleGenerator

__all__ = ["LineageGraph", "InferenceLog", "HandleGenerator"]
