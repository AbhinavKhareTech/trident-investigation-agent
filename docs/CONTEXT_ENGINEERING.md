# Context Engineering

*AI-Native Distributed Systems Engineering Playbook v8.0, Parts 5, 8, 26, 32.*

## The Problem

LLM context windows are finite. Agent state is not.

Naively stuffing everything into a prompt leads to:
- Token budget overruns (115% allocation that silently degrades)
- Audit metadata polluting the reasoning plane (8-12% wasted tokens)
- Raw graph embeddings consuming 800 tokens when 120 suffice
- No compression integrity — monetary values silently rounded
- No entropy governance — a small contradictory context is more dangerous than a large coherent one

## The Solution: Three-Plane Separation

Context is separated into three isolated planes. Data flows between them only through reference handles.

### Reasoning Plane (volatile, in-memory)
Optimized for LLM cognition. Contains persona, task instructions, top-K RAG chunks, structured graph signals, compressed history, constraints, and output schema.

**Critical rule:** Audit metadata never enters the Reasoning Plane. Only reference handles (REF_xxx, ~2 tokens each) cross the boundary.

### Execution Plane (ephemeral, stateful)
Workflow and tool execution state. Contains FSM state, tool schemas, parameter bindings, retry metadata. Deterministic — LLM output is validated against allowed transitions.

### Audit Plane (immutable, persistent)
Compliance, lineage, HITL records. Contains full provenance chains, decision rationale, confidence intervals, escalation triggers, reviewer decisions. Append-only. 7-year retention for BFSI compliance (MiFID II, SR 11-7).

## JIT 7-Block Assembly

Context is assembled at runtime from modular blocks — no static mega-prompts.

| Block | Source | Type | Content |
|-------|--------|------|---------|
| 1 | `personas/persona_v2.yaml` + `rules/rules_v3.json` | Static prefix | System persona + business rules |
| 2 | `task_registry/{intent}.yaml` | JIT | Task-specific instruction |
| 3 | RAG pipeline | Dynamic | Top-K retrieved chunks (relevance gate ≥0.72) |
| 4 | Trident ensemble | Dynamic | Structured graph signals (~120 tokens) |
| 5 | Session history | Dynamic | Loss-aware compressed history |
| 6 | Static | Static suffix | Safety constraints + output schema |
| 7 | Reserved | Buffer | Safety margin (not consumed) |

## Token Budget Enforcement

### Session-Level Budget
Hard cap: 24,600 tokens, mathematically locked at 100%.

No category ever borrows from another. If allocation is exceeded, the degradation ladder activates.

### Degradation Ladder (sequential — never skip steps)

| Step | Action | Tokens Recovered |
|------|--------|-----------------|
| 1 | Reduce RAG top-K (5→3→1) | ~560 |
| 2 | Compress historical state | ~400 |
| 3 | Reduce history window (3→1 turn) | ~200 |
| 4 | Summarize aggressively | ~300 |
| 5 | Lossy graph signals (top-3 only) | ~40 |
| 6 | Drop few-shot examples | ~200 |
| 7 | Simplify output schema | ~100 |
| 8 | Escalate to HITL | Human takes over |

## Cognitive Complexity Score (CCS)

Token count is necessary but insufficient. CCS measures how *confused* the context is, not how *large* it is.

```
CCS = 0.35 × contradiction_density
    + 0.25 × cross_agent_conflict
    + 0.25 × ambiguity_score
    + 0.15 × temporal_inconsistency
```

**Weights reflect FMEA failure severity:**
- contradiction_density (0.35): Silent compression loss, RPN 225
- cross_agent_conflict (0.25): Ensemble disagreement hidden, RPN 175
- ambiguity_score (0.25): Cognitive entropy collapse, RPN 180
- temporal_inconsistency (0.15): State corruption, RPN 120

### CCS Thresholds

| Range | Action | What Happens |
|-------|--------|-------------|
| < 0.4 | Autonomous execution | Normal operation |
| 0.4–0.6 | Verification amplification | Log snapshot, increase verification |
| 0.6–0.8 | Workflow partitioning + HITL | Partition workflow, invoke human |
| > 0.8 | Freeze + kill switch | Freeze execution, evaluate kill switch |

## Loss-Aware Compression

Summarization is not universally safe. Critical fields are structurally preserved.

**Never compress:** monetary values, identifiers, compliance metadata, safety data.

**Protocol:**
1. Extract critical fields → store verbatim in preserved struct
2. Compress non-critical narrative via abstractive summarization
3. Verify semantic checksum: `sha256(critical_pre) == sha256(critical_post)`
4. If mismatch → abort compression → escalate to HITL

## Graph Signal Abstraction

Raw ensemble output (~800 tokens serialized) is converted to structured decision signals (~120 tokens). 85% token reduction, 31% hallucination reduction, improved HITL interpretability.

**Input** (from TridentEnsemble):
```json
{"ensemble_score": 0.85, "pyg_structural": 0.91, "dgl_temporal": 0.43, "xgb_tabular": 0.35}
```

**Output** (DecisionSignal for Reasoning Plane):
```json
{"cross_domain_confidence":0.85,"intent_divergence":"high","order_link_probability":0.85,
 "ensemble_variance":0.072,"disagreement_flag":true,"top_supporting_refs":["REF_001"],
 "uncertainty_interval":{"lower":0.35,"upper":0.91}}
```

Full per-prong breakdown stored only in the Audit Plane.

## Provenance Reference Handles

In-context provenance metadata costs 8-12% token overhead per chunk. Reference handles cost ~1.2%.

**In Reasoning Plane:** `REF_442` (~2 tokens)

**In Audit Plane (ProvenanceRegistry):**
```
source_doc → ingestion_batch → transform_job → embedding_model_version → chunk_id → decision_id
```

Forward query: `source_doc_id → all downstream decisions`
Backward query: `decision_id → all contributing sources + confidence`

## Module Reference

| Module | Class | Purpose |
|--------|-------|---------|
| `planes.py` | `ReasoningPlane`, `ExecutionPlane`, `AuditPlane` | Three-plane isolation |
| `budgets.py` | `TokenBudget`, `TokenBudgetEnforcer`, `BudgetState` | Budget enforcement + degradation |
| `entropy.py` | `CognitiveEntropyMonitor`, `EntropyMetrics` | CCS scoring + autonomy gating |
| `compressor.py` | `LossAwareCompressor`, `CriticalFieldSet` | Compression with integrity checks |
| `signals.py` | `GraphSignalAbstractor`, `DecisionSignal` | 800→120 token signal abstraction |
| `provenance.py` | `ProvenanceRegistry`, `ProvenanceHandle` | Reference handle management |
| `assembler.py` | `ContextAssembler` | JIT 7-block assembly pipeline |
