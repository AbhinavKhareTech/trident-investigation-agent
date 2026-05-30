"""JIT Context Assembler.

The core engine: composes 7-block context per agent request with token budget
enforcement, cognitive entropy monitoring, loss-aware compression, graph signal
abstraction, and provenance injection.

Seven-block pipeline:
1. System Persona + Business Rules (static, prefix)
2. Task Instruction (JIT from task registry)
3. Retrieved Knowledge (dynamic, hybrid search + rerank)
4. Structured Graph Signals (dynamic, abstracted from ensemble)
5. Historical State (dynamic, loss-aware compressed)
6. Constraints + Output Schema (static, suffix)
7. Safety Margin (reserved buffer)

Playbook v8.0 Part 5.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from trident_engine.context.budgets import BudgetState, DegradationAction, TokenBudget, TokenBudgetEnforcer
from trident_engine.context.compressor import LossAwareCompressor
from trident_engine.context.entropy import CognitiveEntropyMonitor, EntropyAction, EntropyMetrics
from trident_engine.context.planes import AuditPlane, ContextBlock, ExecutionPlane, ReasoningPlane
from trident_engine.context.provenance import ProvenanceHandle, ProvenanceRegistry
from trident_engine.context.signals import DecisionSignal, GraphSignalAbstractor

logger = logging.getLogger(__name__)


@dataclass
class AssemblyRequest:
    """Input to the context assembler for a single agent invocation."""

    session_id: str
    agent_id: str
    intent: str
    rag_chunks: list[dict[str, Any]] = field(default_factory=list)
    ensemble_result: dict[str, float] | None = None
    conversation_history: list[dict[str, Any]] = field(default_factory=list)
    user_metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class AssemblyResult:
    """Output from the context assembler."""

    prompt: str
    reasoning_plane: ReasoningPlane
    token_budget_state: BudgetState
    entropy_action: EntropyAction
    entropy_score: float
    provenance_refs: list[str]
    degradations_applied: list[str]
    assembly_time_ms: float


class ContextAssembler:
    """JIT context assembly engine.

    Composes context at runtime from modular blocks. No static mega-prompts.
    Every block is a versioned artifact loaded from config.
    """

    def __init__(
        self,
        budget_enforcer: TokenBudgetEnforcer,
        entropy_monitor: CognitiveEntropyMonitor,
        compressor: LossAwareCompressor,
        signal_abstractor: GraphSignalAbstractor,
        provenance_registry: ProvenanceRegistry,
        audit_plane: AuditPlane,
        config_dir: str | Path = "src/bgi_trident/config_artifacts",
    ) -> None:
        self.budget_enforcer = budget_enforcer
        self.entropy_monitor = entropy_monitor
        self.compressor = compressor
        self.signal_abstractor = signal_abstractor
        self.provenance = provenance_registry
        self.audit = audit_plane
        self.config_dir = Path(config_dir)

        # Cache for loaded config artifacts
        self._persona_cache: dict[str, str] = {}
        self._rules_cache: dict[str, str] = {}
        self._task_cache: dict[str, str] = {}

    def assemble(self, request: AssemblyRequest) -> AssemblyResult:
        """Assemble context for a single agent invocation.

        This is the main entry point. Returns a fully assembled prompt
        with budget enforcement, entropy evaluation, and provenance tracking.
        """
        start = time.time()
        provenance_refs: list[str] = []

        # Initialize budget tracking for this invocation
        budget_state = self.budget_enforcer.start_invocation(request.agent_id)
        reasoning = ReasoningPlane(agent_id=request.agent_id, max_tokens=budget_state.budget.hard_cap)

        # === Block 1: System Persona + Business Rules (static, prefix) ===
        persona_block = self._build_persona_block(request.agent_id, budget_state)
        reasoning.add_block(persona_block)

        # === Block 2: Task Instruction (JIT) ===
        task_block = self._build_task_block(request.intent, budget_state)
        reasoning.add_block(task_block)

        # === Block 3: Retrieved Knowledge (dynamic) ===
        rag_blocks, rag_refs = self._build_rag_blocks(
            request.rag_chunks, budget_state, request.agent_id,
        )
        for block in rag_blocks:
            if not reasoning.add_block(block):
                # Budget exceeded — trigger degradation
                self._apply_degradation(request.agent_id, budget_state, DegradationAction.REDUCE_K)
                break
        provenance_refs.extend(rag_refs)

        # === Block 4: Structured Graph Signals (dynamic) ===
        if request.ensemble_result:
            signal_block, signal_refs = self._build_signal_block(
                request.ensemble_result, budget_state, provenance_refs,
            )
            reasoning.add_block(signal_block)
            provenance_refs.extend(signal_refs)

        # === Block 5: Historical State (dynamic, loss-aware compressed) ===
        if request.conversation_history:
            history_block = self._build_history_block(
                request.conversation_history, budget_state, request.user_metadata,
            )
            reasoning.add_block(history_block)

        # === Block 6: Constraints + Output Schema (static, suffix) ===
        constraints_block = self._build_constraints_block(budget_state)
        reasoning.add_block(constraints_block)

        # === Block 7: Safety Margin (reserved — not consumed) ===
        # Accounted for in budget but not added as content

        # === Entropy Evaluation ===
        entropy_metrics = self._compute_entropy(request, reasoning, provenance_refs)
        entropy_snapshot = self.entropy_monitor.evaluate(
            session_id=request.session_id,
            agent_id=request.agent_id,
            metrics=entropy_metrics,
        )

        # === Validate: no audit leak ===
        violations = reasoning.validate_no_audit_leak()
        if violations:
            logger.error("Audit plane leak detected: %s", violations)

        # === Assemble final prompt ===
        prompt = reasoning.assemble()

        # === Audit logging ===
        context_hash = AuditPlane.hash_context(prompt)
        self.audit.log_inference(
            context_hash=context_hash,
            model_version=budget_state.budget.model_tier,
            business_rules_version="rules_v3",
            output_hash="",  # Filled after LLM response
            provenance_refs=[str(r) for r in provenance_refs],
        )

        elapsed_ms = (time.time() - start) * 1000

        return AssemblyResult(
            prompt=prompt,
            reasoning_plane=reasoning,
            token_budget_state=budget_state,
            entropy_action=entropy_snapshot.action_taken,
            entropy_score=entropy_snapshot.ccs,
            provenance_refs=[str(r) for r in provenance_refs],
            degradations_applied=budget_state.degradations_applied,
            assembly_time_ms=round(elapsed_ms, 2),
        )

    # ── Block builders ──

    def _build_persona_block(self, agent_id: str, budget: BudgetState) -> ContextBlock:
        """Load persona + rules from YAML config artifacts."""
        persona = self._load_config("personas/persona_v2.yaml", self._persona_cache)
        rules = self._load_config("rules/rules_v3.json", self._rules_cache)

        content = f"{persona}\n\n{rules}" if rules else persona
        tokens = self._estimate_tokens(content)

        budget.force_allocate("persona_rules_constraints", tokens)

        return ContextBlock(
            block_id=f"{agent_id}_persona",
            block_type="persona",
            content=content,
            token_count=tokens,
            source="persona_v2.yaml + rules_v3.json",
            is_static=True,
            is_critical=True,
        )

    def _build_task_block(self, intent: str, budget: BudgetState) -> ContextBlock:
        """JIT-select task instruction from registry based on intent."""
        task_path = f"task_registry/{intent}.yaml"
        task_content = self._load_config(task_path, self._task_cache)

        if not task_content:
            task_content = f"Execute task: {intent}"

        tokens = self._estimate_tokens(task_content)
        category = "task_fewshot_schema"
        limit = budget.category_remaining(category)

        if tokens > limit:
            task_content = task_content[:limit * 4]  # Rough truncation
            tokens = limit

        budget.try_allocate(category, tokens)

        return ContextBlock(
            block_id=f"task_{intent}",
            block_type="task",
            content=task_content,
            token_count=tokens,
            source=task_path,
            is_static=False,
        )

    def _build_rag_blocks(
        self,
        chunks: list[dict[str, Any]],
        budget: BudgetState,
        agent_id: str,
    ) -> tuple[list[ContextBlock], list[str]]:
        """Build RAG blocks with relevance gating, dedup, and provenance.

        Relevance gate: chunks with score < 0.72 are dropped.
        Top-K governed by budget; K reduced during degradation.
        """
        RELEVANCE_THRESHOLD = 0.72
        refs: list[str] = []

        # Filter by relevance
        relevant = [c for c in chunks if c.get("score", 0) >= RELEVANCE_THRESHOLD]
        relevant.sort(key=lambda c: c.get("score", 0), reverse=True)

        # Determine K from budget
        available = budget.category_remaining("retrieved_knowledge")
        blocks: list[ContextBlock] = []
        tokens_used = 0

        for chunk in relevant:
            content = chunk.get("content", "")
            chunk_tokens = self._estimate_tokens(content)

            if tokens_used + chunk_tokens > available:
                break

            # Register provenance
            handle = self.provenance.register(
                source_type="rag_chunk",
                source_doc_id=chunk.get("doc_id"),
                chunk_id=chunk.get("chunk_id"),
                confidence=chunk.get("score"),
                metadata={"agent_id": agent_id},
            )
            refs.append(handle.ref_id)

            # Inject reference handle, NOT full metadata
            content_with_ref = f"[{handle.ref_id}] {content}"

            block = ContextBlock(
                block_id=f"rag_{chunk.get('chunk_id', len(blocks))}",
                block_type="rag",
                content=content_with_ref,
                token_count=self._estimate_tokens(content_with_ref),
                source=chunk.get("doc_id", "unknown"),
                provenance_ref=handle.ref_id,
            )
            blocks.append(block)
            tokens_used += block.token_count
            budget.try_allocate("retrieved_knowledge", block.token_count)

        return blocks, refs

    def _build_signal_block(
        self,
        ensemble_result: dict[str, float],
        budget: BudgetState,
        existing_refs: list[str],
    ) -> tuple[ContextBlock, list[str]]:
        """Build graph signal block using abstracted decision signals."""
        signal = self.signal_abstractor.abstract(
            ensemble_result=ensemble_result,
            provenance_refs=existing_refs[:3],
        )

        content = signal.to_context_block()
        tokens = self._estimate_tokens(content)

        # Register provenance for the graph signal itself
        handle = self.provenance.register(
            source_type="graph_embedding",
            metadata=signal.to_full_audit(),
        )

        budget.try_allocate("graph_signals", tokens)

        block = ContextBlock(
            block_id="graph_signal",
            block_type="graph_signal",
            content=f"[Graph Signal {handle.ref_id}]\n{content}",
            token_count=tokens + 5,  # Account for header
            source="trident_ensemble",
            provenance_ref=handle.ref_id,
        )
        return block, [handle.ref_id]

    def _build_history_block(
        self,
        history: list[dict[str, Any]],
        budget: BudgetState,
        user_metadata: dict[str, Any],
    ) -> ContextBlock:
        """Build compressed history block with critical field preservation."""
        available = budget.category_remaining("historical_state")

        result = self.compressor.compress_history(
            turns=history,
            target_tokens=available,
            max_turns=3,
        )

        if not result.integrity_verified:
            logger.error("History compression integrity failure — using uncompressed recent turns only")
            content = "\n".join(
                f"[{t.get('role', '?')}]: {t.get('content', '')}"
                for t in history[-2:]
            )
        else:
            content = result.compressed_content

        tokens = self._estimate_tokens(content)
        budget.try_allocate("historical_state", tokens)

        return ContextBlock(
            block_id="history",
            block_type="history",
            content=content,
            token_count=tokens,
            source="session_history",
            is_critical=False,
        )

    def _build_constraints_block(self, budget: BudgetState) -> ContextBlock:
        """Safety constraints at primacy/recency + output schema."""
        constraints = (
            "CONSTRAINTS:\n"
            "- Never execute a transaction without explicit user confirmation.\n"
            "- Monetary values must be stated exactly as provided — no rounding.\n"
            "- If confidence is below 0.5, escalate to human review.\n"
            "- Respond in the user's language.\n"
            "\nOUTPUT: Respond in structured JSON matching the provided schema."
        )
        tokens = self._estimate_tokens(constraints)
        budget.force_allocate("persona_rules_constraints", tokens)

        return ContextBlock(
            block_id="constraints",
            block_type="constraints",
            content=constraints,
            token_count=tokens,
            source="static_constraints",
            is_static=True,
            is_critical=True,
        )

    # ── Entropy computation ──

    def _compute_entropy(
        self,
        request: AssemblyRequest,
        reasoning: ReasoningPlane,
        refs: list[str],
    ) -> EntropyMetrics:
        """Compute CCS metrics from assembled context."""
        # Contradiction density from RAG chunks
        statements = [
            {"claim": c.get("content", ""), "source": c.get("doc_id", "")}
            for c in request.rag_chunks
        ]
        contradiction = self.entropy_monitor.check_contradictions(statements)

        # Cross-agent conflict from ensemble
        cross_conflict = 0.0
        if request.ensemble_result:
            variance, is_conflict = self.entropy_monitor.check_ensemble_conflict(
                request.ensemble_result.get("pyg_structural", 0.5),
                request.ensemble_result.get("dgl_temporal", 0.5),
                request.ensemble_result.get("xgb_tabular", 0.5),
            )
            cross_conflict = min(1.0, variance * 5)  # Normalize to 0-1

        return EntropyMetrics(
            contradiction_density=contradiction,
            ambiguity_score=0.0,  # TODO: integrate NLU confidence
            temporal_consistency=1.0,  # TODO: integrate session state
            cross_agent_conflict=cross_conflict,
        )

    # ── Degradation ──

    def _apply_degradation(
        self, agent_id: str, budget: BudgetState, action: DegradationAction,
    ) -> None:
        self.budget_enforcer.apply_degradation(agent_id, action)

    # ── Utilities ──

    def _load_config(self, relative_path: str, cache: dict[str, str]) -> str:
        """Load a config artifact from disk, with caching."""
        if relative_path in cache:
            return cache[relative_path]

        full_path = self.config_dir / relative_path
        if not full_path.exists():
            logger.warning("Config artifact not found: %s", full_path)
            return ""

        content = full_path.read_text()
        cache[relative_path] = content
        return content

    @staticmethod
    def _estimate_tokens(text: str) -> int:
        return max(1, len(text) // 4)
