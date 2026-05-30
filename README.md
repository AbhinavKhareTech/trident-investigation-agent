# Trident Investigation Agent

**Autonomous Investigation Engine — Drop CSVs, Get Case Files.**

```
4 CSV files → 617-node graph → 15 anomalies → 4 hypotheses → 1 case file
Zero user prompts. 5 seconds. ₹39.8L exposure identified.
```

## Quickstart

```bash
git clone https://github.com/AbhinavKhareTech/trident-investigation-agent.git
cd trident-investigation-agent
pip install -e ".[dev]"
python -m investigation_agent
```

The agent generates synthetic data, builds a heterogeneous graph, discovers hidden connections, detects anomalies across 5 signal types, generates hypotheses with evidence, and produces a complete investigation case file.

## What Happens

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│  📁 Drop CSVs    →  🕸️ Build Graph  →  🔍 Detect Anomalies │
│  (customers,        (617 nodes,        (clusters, shared    │
│   claims,            2,951 edges,       identity, outliers,  │
│   payments,          1,922 hidden       provider conc.,      │
│   agents)            connections)       temporal bursts)      │
│                                                             │
│  →  🧠 Generate Hypotheses  →  📋 Create Case File          │
│     (supporting +               (markdown report with        │
│      contradicting               audit trail, actions,       │
│      evidence,                   entity inventory)           │
│      confidence scoring)                                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

## Architecture

This repo contains two layers:

### 1. Investigation Agent (`src/investigation_agent/`)

The domain-agnostic autonomous investigation pipeline.

```
investigation_agent/
├── models.py              # Entity, Relationship, Anomaly, Hypothesis, CaseFile
├── graph_builder.py       # CSV → heterogeneous NetworkX graph
│                          # + implicit relationship discovery
├── detector.py            # 5 anomaly detection algorithms
├── investigator.py        # Hypothesis generation + evidence collection
├── reporter.py            # Markdown case file generator
├── orchestrator.py        # Rich terminal UI + autonomous 6-phase pipeline
├── __main__.py            # CLI entrypoint
└── synthetic/
    └── generator.py       # Deterministic data generator with fraud patterns
```

### 2. Trident Engine (`src/trident_engine/`)

Production-grade AI agent infrastructure from [BGI Trident](https://github.com/AbhinavKhareTech/trident-consumption-graph).

```
trident_engine/
├── context/               # Context Engineering (Playbook v8.0)
│   ├── planes.py          #   Three-plane separation (Reasoning/Execution/Audit)
│   ├── budgets.py         #   Token budget enforcement (24,600 cap, 100% locked)
│   ├── entropy.py         #   Cognitive Entropy Monitor (CCS scoring)
│   ├── compressor.py      #   Loss-aware compression (critical fields preserved)
│   ├── signals.py         #   Graph signal abstraction (800→120 tokens, 85% reduction)
│   ├── provenance.py      #   Reference handles (REF_xxx, 1.2% overhead vs 8-12%)
│   └── assembler.py       #   JIT 7-block context assembly pipeline
│
├── fsm/                   # Deterministic Workflow Authority
│   ├── engine.py          #   FSM engine (LLM proposes, FSM authorizes)
│   ├── transitions.py     #   Transition validator + temporal guards
│   ├── state_store.py     #   Persistent FSM state (not LLM memory)
│   └── schemas/           #   YAML workflow definitions
│       ├── food_order.yaml
│       ├── instamart_order.yaml
│       └── dineout_booking.yaml
│
├── lineage/               # Provenance & Audit
│   ├── graph.py           #   Forward/backward lineage tracing
│   ├── inference_log.py   #   Append-only immutable inference log
│   └── handles.py         #   Thread-safe REF_xxx handle generation
│
├── reliability/           # SRE for AI
│   ├── retrieval_sre.py   #   RAG quality monitoring + auto-remediation
│   ├── slos.py            #   SLO tracking with auto-rollback triggers
│   └── latency.py         #   Latency budget decomposition (TTFT <2s)
│
└── config_artifacts/      # Versioned configuration
    ├── personas/          #   Agent persona definitions
    ├── rules/             #   Business rules (JSON)
    ├── task_registry/     #   Workflow task definitions (YAML)
    ├── budgets/           #   Token budget allocations
    └── entropy/           #   CCS threshold configuration
```

## Investigation Pipeline

The agent follows a strict 6-phase autonomous pipeline:

```
OBSERVE → DETECT → HYPOTHESIZE → INVESTIGATE → RECOMMEND → REPORT
```

| Phase | What Happens | Output |
|-------|-------------|--------|
| **OBSERVE** | File system watch, CSV detection | Data inventory |
| **INGEST** | Parse CSVs → build heterogeneous graph → discover implicit relationships | 617 nodes, 2,951 edges |
| **DETECT** | Run 5 detection algorithms in parallel | 15 anomalies ranked by severity |
| **INVESTIGATE** | Generate hypotheses, gather supporting/contradicting evidence | 4 hypotheses with confidence scores |
| **RECOMMEND** | Determine actions based on confidence + convergence | SIU referral, payout freeze, etc. |
| **REPORT** | Generate markdown case file with full audit trail | Complete investigation report |

## Detection Algorithms

| Detector | Signal | What It Finds |
|----------|--------|---------------|
| Community Detection | Louvain / greedy modularity | Tightly-knit clusters sharing hidden connections |
| Shared Identity | Index-based matching | Entities sharing phone numbers or addresses |
| Amount Outlier | Z-score analysis (>2σ) | Claims with statistically anomalous values |
| Provider Concentration | Degree centrality | Providers with abnormally many claims routed to them |
| Temporal Burst | Date clustering | Many claims filed on the same day |

## Trident Engine Details

### Context Engineering

The context engine solves the core problem: LLM context windows are finite, but agent state is not.

**Three-Plane Separation:**
- **Reasoning Plane** — Optimized for LLM cognition (volatile, in-memory). Audit metadata never enters this plane.
- **Execution Plane** — FSM state, tool bindings, retry metadata (ephemeral, stateful).
- **Audit Plane** — Compliance, lineage, HITL records (immutable, persistent, 7-year retention).

**Token Budget Enforcement:**
- Session hard cap: 24,600 tokens, mathematically locked at 100%
- 8-step sequential degradation ladder (never skip steps)
- Per-agent category budgets loaded from YAML config artifacts

**Cognitive Entropy Scoring (CCS):**

A small contradictory context is more dangerous than a large coherent one.

```
CCS = 0.35 × contradiction_density
    + 0.25 × cross_agent_conflict
    + 0.25 × ambiguity_score
    + 0.15 × temporal_inconsistency
```

| CCS Range | Action |
|-----------|--------|
| < 0.4 | Autonomous execution |
| 0.4 - 0.6 | Verification amplification + log snapshot |
| 0.6 - 0.8 | Workflow partitioning + invoke HITL |
| > 0.8 | Freeze execution + kill switch evaluation |

### FSM — Deterministic Workflow Authority

LLMs may propose state transitions. The FSM engine authorizes them.

Prompt memory, conversational reasoning, and hidden chain-of-thought are **never** the system-of-record for workflow state.

Every transition is validated, logged, timeout-bounded, and compensatable (rollback handlers).

### Lineage & Provenance

- **Forward query:** source_doc_id → all downstream decisions
- **Backward query:** decision_id → all contributing sources + confidence
- **Impact analysis:** If source X is retracted, which decisions are affected?

In-context: `REF_442` (~2 tokens). In audit plane: full chain (source → ingestion → transform → embedding → chunk → decision).

## Usage

```bash
# Generate synthetic data + run full pipeline
python -m investigation_agent

# Use your own data
python -m investigation_agent --data ./my_csvs/

# Control synthetic data parameters
python -m investigation_agent --generate --n-normal 500 --ring-size 12

# Custom output directory
python -m investigation_agent --output ./reports/

# CLI entrypoint (after pip install)
investigate --help
```

### Input Format

The agent expects a directory with CSV files:

| File | Columns |
|------|---------|
| `customers.csv` | customer_id, name, phone, email, city, area, address, risk_tier |
| `claims.csv` | claim_id, customer_id, date, vehicle, damage, description, repair_amount, medical_amount, total_amount, garage, hospital, agent_id, status, city |
| `payments.csv` | payment_id, claim_id, customer_id, amount, date, payee, method |
| `agents.csv` | agent_id, name, region, active_since, cases_handled |

Any subset works — the agent handles missing files gracefully.

## Tests

```bash
python -m pytest tests/ -v    # 93 tests
```

| Test Suite | Tests | Coverage |
|-----------|-------|----------|
| `test_agent.py` | 24 | Investigation pipeline end-to-end |
| `test_context.py` | 31 | Three-plane, budgets, entropy, compression, signals, provenance |
| `test_fsm.py` | 17 | Engine, transitions, state store, compensation |
| `test_lineage.py` | 13 | Graph, inference log, handle generation |
| `test_reliability.py` | 8 | Retrieval SRE, SLOs, latency budgets |

## Domain Packs (Roadmap)

The core is domain-agnostic. Industry packs are config overlays:

| Pack | Status | Entity Types |
|------|--------|-------------|
| **Insurance Claims** | ✅ Included | Claim, Claimant, Vehicle, Provider, Agent |
| **AML** | Planned | Transaction, Account, Beneficiary, Jurisdiction |
| **Vendor Risk** | Planned | Vendor, Contract, Control, Evidence |
| **Cyber Incident** | Planned | Alert, Host, User, Process, IP |
| **Due Diligence** | Planned | Company, Director, Litigation, Financials |

## Project

Built by [AhinsaAI / Meraki Labs](https://github.com/AbhinavKhareTech).

Trident Engine from [BGI Trident Consumption Graph](https://github.com/AbhinavKhareTech/trident-consumption-graph).

## License

MIT
