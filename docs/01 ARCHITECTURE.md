# System Architecture

## Overview

The Trident Investigation Agent is a two-layer system:

1. **Trident Engine** — Production-grade AI agent infrastructure (context engineering, FSM, lineage, reliability)
2. **Investigation Agent** — Domain-agnostic autonomous investigation pipeline built on top of the engine

```
┌─────────────────────────────────────────────────────────────────────┐
│                     Investigation Agent                             │
│                                                                     │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────┐   │
│  │Synthetic │  │  Graph   │  │ Anomaly  │  │Investi-  │  │Report│   │
│  │Generator │→ │ Builder  │→ │ Detector │→ │  gator   │→ │  er  │   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘  └──────┘   │
│                     │              │              │                 │
│                     ▼              ▼              ▼                 │
│              ┌─────────────────────────────────────────┐            │
│              │          Orchestrator (Rich UI)          │           │
│              └─────────────────────────────────────────┘            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                       Trident Engine                                │
│                                                                     │
│  ┌──────────────┐  ┌──────────┐  ┌──────────┐  ┌──────────────┐     │
│  │   Context    │  │   FSM    │  │ Lineage  │  │ Reliability  │     │
│  │ Engineering  │  │ Engine   │  │ & Audit  │  │   (SRE)      │     │
│  │              │  │          │  │          │  │              │     │
│  │ • 3 Planes  │  │ • States │  │ • Graph   │  │ • RAG SRE    │     │
│  │ • Budgets   │  │ • Rules  │  │ • Log     │  │ • SLOs       │     │
│  │ • Entropy   │  │ • Compen-│  │ • Handles │  │ • Latency    │     │ 
│  │ • Compress  │  │   sation │  │           │  │              │     │
│  │ • Signals   │  │          │  │           │  │              │     │
│  │ • Provenance│  │          │  │           │  │              │     │
│  │ • Assembler │  │          │  │           │  │              │     │
│  └──────────────┘  └──────────┘  └──────────┘  └──────────────┘     │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                   Config Artifacts (YAML/JSON)              │    │
│  │  personas/ │ rules/ │ task_registry/ │ budgets/ │ entropy/  │    │
│  └─────────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────┘
```

## Data Flow

### Investigation Pipeline

```
 CSV Files              Graph                    Anomalies
 ─────────              ─────                    ─────────
 customers.csv  ──┐
 claims.csv     ──┤──→  InvestigationGraph  ──→  AnomalyDetector
 payments.csv   ──┤     (NetworkX)               │
 agents.csv     ──┘     │                        ├─ Community detection
                        ├─ Entity nodes           ├─ Shared identity
                        ├─ Relationship edges     ├─ Amount outliers
                        └─ Implicit connections   ├─ Provider concentration
                           (shared phone,         └─ Temporal bursts
                            shared address,
                            same provider)              │
                                                        ▼
                                                  Investigator
                                                  │
                                                  ├─ Generate hypotheses
                                                  ├─ Gather evidence (supporting + contradicting)
                                                  ├─ Assess confidence
                                                  └─ Recommend actions
                                                        │
                                                        ▼
                                                  Reporter
                                                  │
                                                  └─ Markdown case file
                                                     (audit trail, entity inventory,
                                                      actions, evidence tables)
```

### Context Engineering Pipeline (Trident Engine)

```
                    ┌─────────────────────────┐
                    │    Assembly Request      │
                    │  (session, agent, intent,│
                    │   RAG chunks, ensemble,  │
                    │   history, metadata)     │
                    └────────────┬────────────┘
                                 │
                                 ▼
              ┌──────────────────────────────────┐
              │       JIT Context Assembler       │
              │                                    │
              │  Block 1: Persona + Rules (static) │
              │  Block 2: Task Instruction (JIT)   │
              │  Block 3: RAG Chunks (dynamic)     │
              │  Block 4: Graph Signals (dynamic)  │
              │  Block 5: History (compressed)      │
              │  Block 6: Constraints (static)      │
              │  Block 7: Safety Margin (reserved)  │
              └──────────┬───────────┬─────────────┘
                         │           │
                ┌────────┘           └────────┐
                ▼                              ▼
    ┌───────────────────┐         ┌────────────────────┐
    │  Token Budget      │         │ Cognitive Entropy   │
    │  Enforcer          │         │ Monitor (CCS)       │
    │                    │         │                      │
    │  24,600 cap        │         │  < 0.4: autonomous   │
    │  100% locked       │         │  0.4-0.6: verify     │
    │  8-step degrade    │         │  0.6-0.8: HITL       │
    └───────────────────┘         │  > 0.8: freeze       │
                                   └────────────────────┘
```

## Graph Schema (Insurance Domain)

```
    ┌──────────┐         ┌──────────┐         ┌──────────┐
    │  Person  │─filed──→│  Claim   │─repaired→│ Provider │
    │(customer)│  claim  │          │  at      │ (garage) │
    └──────────┘         └──────────┘         └──────────┘
         │                    │                     │
         │shares_phone        │paid_via             │
         │shares_address      ▼                     │
         ▼               ┌──────────┐              │
    ┌──────────┐         │ Payment  │              │
    │  Person  │         └──────────┘              │
    │(customer)│              │                     │
    └──────────┘              │                     │
         │                    ▼                     │
         │same_provider  ┌──────────┐              │
         └──────────────→│ Provider │←─────────────┘
                         │(hospital)│
                         └──────────┘

    Explicit edges: filed_claim, repaired_at, treated_at, paid_via, handled_by
    Implicit edges: shares_phone, shares_address, same_provider (discovered at runtime)
```

## FSM State Machine

```
    ┌──────┐    order     ┌────────────────┐   payment    ┌────────────────────┐
    │ IDLE │───valid──→   │ORDER_INITIATED │───success──→ │PAYMENT_AUTHORIZED  │
    └──────┘              └────────────────┘              └────────────────────┘
                                │                                │
                                │                                │  merchant
                                ▼                                ▼  confirmed
                          ┌──────────┐              ┌──────────────────────┐
                          │  FAILED  │              │ MERCHANT_CONFIRMED   │
                          └──────────┘              └──────────────────────┘
                                ▲                                │
                                │                                │  driver
                                │                                ▼  matched
                                │                   ┌──────────────────────┐
                                └───────────────────│  DRIVER_ASSIGNED     │
                                                    └──────────────────────┘
                                                                 │
                                                                 │  delivered
                                                                 ▼
                          ┌──────────────────┐      ┌──────────────────────┐
                          │ REFUND_INITIATED │←─────│     DELIVERED        │
                          └──────────────────┘      └──────────────────────┘
                                                                 │
                                                                 ▼
                                                    ┌──────────────────────┐
                                                    │       CLOSED         │
                                                    └──────────────────────┘

    Every transition:
    ✓ Validated against allowed transitions
    ✓ Logged to immutable audit trail
    ✓ Timeout-bounded with retry limits
    ✓ Compensatable (rollback handler)
```

## Token Budget Allocation

```
    Session Hard Cap: 24,600 tokens (100.0%)

    ┌─────────────────────────┬────────┬───────┐
    │ Agent                   │ Tokens │   %   │
    ├─────────────────────────┼────────┼───────┤
    │ Session Supervisor      │  4,000 │ 16.3% │
    │ Food Coordinator        │  3,000 │ 12.2% │
    │ Instamart Coordinator   │  3,000 │ 12.2% │
    │ Dineout Coordinator     │  3,000 │ 12.2% │
    │ Settlement Agent        │  2,000 │  8.1% │
    │ Verification Orchestrat.│  2,000 │  8.1% │
    │ Reserved Safety Pool    │  7,600 │ 30.9% │
    ├─────────────────────────┼────────┼───────┤
    │ TOTAL                   │ 24,600 │100.0% │
    └─────────────────────────┴────────┴───────┘

    Per-Agent Internal Allocation (Supervisor example):
    ┌──────────────────────────┬──────┐
    │ Category                 │  %   │
    ├──────────────────────────┼──────┤
    │ Persona + Rules          │  20% │ (static, never degrade)
    │ Retrieved Knowledge      │  35% │ (dynamic, degrade: reduce_k → compress)
    │ Graph Signals            │  15% │ (dynamic, degrade: lossy_top3)
    │ Historical State         │  15% │ (dynamic, degrade: reduce_window → summarize)
    │ Task + Few-shot + Schema │  10% │ (static, degrade: drop_fewshot → simplify)
    │ Entropy Monitoring       │   5% │ (dynamic)
    └──────────────────────────┴──────┘
```

## File Map

```
trident-investigation-agent/
├── README.md
├── LICENSE
├── pyproject.toml
├── docs/
│   ├── ARCHITECTURE.md          ← You are here
│   ├── CONTEXT_ENGINEERING.md
│   └── INVESTIGATION_PIPELINE.md
├── src/
│   ├── investigation_agent/     # The autonomous investigation agent
│   │   ├── models.py
│   │   ├── graph_builder.py
│   │   ├── detector.py
│   │   ├── investigator.py
│   │   ├── reporter.py
│   │   ├── orchestrator.py
│   │   ├── __main__.py
│   │   └── synthetic/
│   │       └── generator.py
│   └── trident_engine/          # Production AI agent infrastructure
│       ├── context/             # Context engineering (7 modules)
│       ├── fsm/                 # Deterministic FSM (3 modules + 3 schemas)
│       ├── lineage/             # Provenance & audit (3 modules)
│       ├── reliability/         # SRE for AI (3 modules)
│       └── config_artifacts/    # Versioned config (10 files)
└── tests/
    ├── test_agent.py            # 24 investigation agent tests
    ├── test_context.py          # 31 context engineering tests
    ├── test_fsm.py              # 17 FSM tests
    ├── test_lineage.py          # 13 lineage tests
    └── test_reliability.py      # 8 reliability tests
```
