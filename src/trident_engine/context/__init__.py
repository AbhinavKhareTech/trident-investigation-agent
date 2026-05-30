"""Context Engineering Engine.

JIT context assembly with three-plane separation, loss-aware compression,
cognitive entropy governance, and token budget enforcement.

Playbook v8.0 Parts 5, 8, 32.
"""

from trident_engine.context.assembler import ContextAssembler
from trident_engine.context.budgets import TokenBudget, TokenBudgetEnforcer
from trident_engine.context.compressor import LossAwareCompressor
from trident_engine.context.entropy import CognitiveEntropyMonitor
from trident_engine.context.planes import AuditPlane, ExecutionPlane, ReasoningPlane
from trident_engine.context.provenance import ProvenanceHandle, ProvenanceRegistry
from trident_engine.context.signals import GraphSignalAbstractor

__all__ = [
    "ContextAssembler",
    "TokenBudget",
    "TokenBudgetEnforcer",
    "LossAwareCompressor",
    "CognitiveEntropyMonitor",
    "ReasoningPlane",
    "ExecutionPlane",
    "AuditPlane",
    "ProvenanceHandle",
    "ProvenanceRegistry",
    "GraphSignalAbstractor",
]
