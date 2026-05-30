# Investigation Pipeline

## Overview

The investigation agent follows a strict 6-phase autonomous pipeline. Every phase executes without user prompts. The agent goes from raw CSV files to a complete investigation case file autonomously.

```
OBSERVE → INGEST → DETECT → INVESTIGATE → RECOMMEND → REPORT
```

## Phase 1: OBSERVE

The agent detects new data files in the watched directory.

**Input:** Directory path containing CSV files.
**Output:** File inventory with sizes.

Supported files: `customers.csv`, `claims.csv`, `payments.csv`, `agents.csv`. Any subset works — the agent handles missing files gracefully.

## Phase 2: INGEST — Graph Construction

### Explicit Relationships (from CSV data)

Each CSV row becomes typed nodes and edges:

| CSV | Node Type | Edges Created |
|-----|-----------|---------------|
| customers.csv | `person` | — |
| claims.csv | `claim`, `provider` (garage), `provider` (hospital) | `filed_claim`, `repaired_at`, `treated_at`, `handled_by` |
| payments.csv | `payment` | `paid_via`, `paid_to` |
| agents.csv | `agent` | — |

### Implicit Relationship Discovery

This is where the investigation power comes from. The graph builder maintains indexes on phone numbers, addresses, and provider associations. After all CSVs are ingested, it discovers hidden connections:

| Signal | Method | Threshold |
|--------|--------|-----------|
| Shared phone | Phone index: `{phone: [entity_ids]}` | 2+ entities sharing a phone |
| Shared address | Address index: `{address: [entity_ids]}` | 2+ entities sharing an address |
| Same provider | Provider index: `{provider_id: [customer_ids]}` | 4+ customers routed to same provider |

These implicit edges are what reveal fraud rings that are invisible in tabular data.

**Typical output:** 617 nodes, 2,951 edges (1,922 implicit connections discovered).

## Phase 3: DETECT — Anomaly Analysis

Five detection algorithms run on the graph. Each produces scored anomalies.

### 3.1 Community Detection (Suspicious Clusters)

Extracts the person-to-person subgraph connected by implicit edges (shares_phone, shares_address, same_provider). Runs greedy modularity community detection. Scores each community by:

```
risk_score = 0.3 × min(1, shared_phones/3)
           + 0.3 × min(1, shared_addresses/2)
           + 0.2 × min(1, common_providers/3)
           + 0.2 × min(1, cluster_size/6)
```

Communities with `risk_score ≥ 0.5` and `size ≥ 3` are flagged.

### 3.2 Shared Identity Detection

Directly scans for entities sharing phone numbers or addresses. Groups by shared identifier and flags any group with 2+ members (phones) or 3+ members (addresses).

### 3.3 Amount Outlier Detection

Computes z-scores across all claim amounts. Claims with `z-score > 2.0` are flagged. Severity escalates at `z-score > 3.0`.

### 3.4 Provider Concentration

Counts claims per provider. Providers with 4+ claims are flagged. Severity escalates at 6+ claims. Calculates total monetary exposure through the provider.

### 3.5 Temporal Burst Detection

Groups claims by date. Days with 4+ claims are flagged as potential coordinated filing patterns.

### Anomaly Ranking

All anomalies are sorted by `(-severity_rank, -confidence)`. Critical/High anomalies surface first.

## Phase 4: INVESTIGATE — Hypothesis Generation

### Hypothesis Templates

Each anomaly type maps to a hypothesis template:

| Anomaly Type | Hypothesis Title | What It Means |
|-------------|-----------------|---------------|
| `suspicious_cluster` | Coordinated Fraud Ring | Group of entities operating as a ring |
| `shared_identity` | Identity Manipulation | Possible synthetic or shared identities |
| `amount_outlier` | Claim Amount Inflation | Statistically anomalous claim values |
| `provider_concentration` | Provider Collusion | Provider may have kickback arrangements |
| `temporal_burst` | Staged Incident Pattern | Coordinated filing suggests staging |

### Evidence Collection

For each hypothesis, the investigator gathers:

**Supporting evidence:**
- Betweenness centrality of key nodes (central connectors in the ring)
- High claim amounts (>₹1L)
- Provider concentration (many claims routed to same provider)

**Contradicting evidence:**
- Entities with low historical risk tier
- Long legitimate history

### Confidence Scoring

```
confidence = supporting_weight / (supporting_weight + contradicting_weight)
```

Boosted by multi-signal convergence: if an entity appears in multiple anomaly types, confidence increases.

### Convergence Check

The investigator cross-references all anomalies to find entities that appear across multiple signal types. Convergence strengthens the case.

## Phase 5: RECOMMEND — Action Determination

Actions are gated by confidence level:

| Confidence | Actions |
|-----------|---------|
| > 80% | IMMEDIATE: SIU referral. FREEZE: Suspend pending payouts. |
| > 60% | ESCALATE: Senior analyst review within 24h. HOLD: 48h payout hold. |
| < 60% | MONITOR: Add to 90-day watchlist. |

Cross-cutting actions:
- If entities converge across multiple anomalies → INVESTIGATE: cross-reference with external databases
- If provider collusion hypothesis is supported → AUDIT: schedule on-site audit
- Always: DOCUMENT: full audit trail preserved

## Phase 6: REPORT — Case File Generation

The reporter produces a markdown case file containing:

1. **Executive summary** — severity, confidence, entity count, total exposure
2. **Hypotheses** — each with title, description, confidence, evidence, status
3. **Anomaly table** — all detected anomalies with type, severity, confidence
4. **Entity inventory** — flagged entities with type, name, risk score
5. **Recommended actions** — prioritized action items with severity icons
6. **Graph statistics** — total nodes, edges, case entity count
7. **Audit trail** — agent version, generation timestamp, governance note

## Embedded Fraud Patterns (Synthetic Generator)

The synthetic data generator embeds deterministic fraud patterns for reproducible demos:

| Signal | What's Embedded |
|--------|----------------|
| Shared phone numbers | 2 phone numbers shared across 5 ring members |
| Shared address | Single address shared by 5 ring members |
| Same garage | All ring claims routed to "RapidFix Auto Hub" |
| Same hospital | All ring claims routed to "MedCare Wellness Clinic" |
| Same agent | All ring claims handled by one agent |
| Temporal burst | All ring claims filed within 5 days |
| Inflated amounts | Ring claims: ₹65K-180K repair + ₹15K-45K medical (vs normal ₹5K-120K) |
| Identical descriptions | All ring claims: "Multi-vehicle collision at junction" |

The generator uses `random.seed(42)` inside each call, making output deterministic and reproducible.

## Module Reference

| Module | Key Classes | Responsibility |
|--------|------------|----------------|
| `models.py` | `Entity`, `Relationship`, `Anomaly`, `Hypothesis`, `CaseFile`, `AgentEvent` | Domain-agnostic data models |
| `graph_builder.py` | `InvestigationGraph` | CSV → graph + implicit relationship discovery |
| `detector.py` | `AnomalyDetector` | 5 detection algorithms |
| `investigator.py` | `Investigator` | Hypothesis generation + evidence + confidence |
| `reporter.py` | `Reporter` | Markdown case file generation |
| `orchestrator.py` | `run_investigation`, `main` | Rich terminal UI + full pipeline |
| `synthetic/generator.py` | `generate_dataset` | Deterministic data with fraud patterns |
