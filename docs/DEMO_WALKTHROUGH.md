# Demo Walkthrough

## What Just Happened

You ran `python run.py`. The agent did everything autonomously — no prompts, no clicks, no configuration.

## The 6 Phases

### Phase 1: OBSERVE
Agent detected 4 CSV files in `./incoming_data/`: customers (208 records), claims (208), payments (169), agents (10).

### Phase 2: INGEST
Built a 617-node heterogeneous graph from flat CSVs. Node types: person, claim, payment, provider (garage/hospital), agent.

Then the key step: **implicit relationship discovery**. The agent indexed every phone number, address, and provider association, then linked entities that share identifiers but never appeared together in any CSV row. Found 1,922 hidden connections. This is what makes graph analysis superior to SQL — these connections are invisible in tabular data.

### Phase 3: DETECT
Ran 5 detection algorithms simultaneously:

1. **Community detection** — Found tightly-knit clusters of people connected by shared phones/addresses/providers. Scored each cluster by signal density.
2. **Shared identity** — 5 entities share the same address (42, 3rd Cross, Koramangala). 3 entities share the same phone number. Red flag.
3. **Amount outliers** — Claim CLM-5207 at ₹198,600 is 3.2 standard deviations above the mean (₹73,688). Statistical anomaly.
4. **Provider concentration** — "RapidFix Auto Hub" and "MedCare Wellness Clinic" appear in an unusual number of claims from connected entities.
5. **Temporal burst** — Multiple clusters of 4+ claims filed on the same day.

Total: 15 anomalies detected, ranked by severity and confidence.

### Phase 4: INVESTIGATE
For each high-severity anomaly, the agent:
- Generated a hypothesis (e.g., "Coordinated Fraud Ring", "Claim Amount Inflation")
- Gathered supporting evidence from the graph (betweenness centrality of key nodes, high claim values, provider concentration patterns)
- Gathered contradicting evidence (some entities have low historical risk tiers)
- Computed confidence = supporting_weight / (supporting + contradicting)
- Checked convergence: do different anomaly types point at the same entities?

Result: 4 hypotheses. One confirmed with 100% confidence (claim inflation through RapidFix Auto Hub).

### Phase 5: RECOMMEND
Based on confidence levels:
- **IMMEDIATE**: Refer to Special Investigation Unit
- **FREEZE**: Suspend pending payouts for linked claims
- **INVESTIGATE**: 5 entities appear across multiple anomaly types — cross-reference with external databases
- **DOCUMENT**: Full audit trail preserved

### Phase 6: REPORT
Generated a markdown case file at `./output/CASE_xxxxx_report.md` containing: executive summary, all hypotheses with evidence, anomaly table, entity inventory, recommended actions, graph statistics, and audit trail.

## The Embedded Fraud Ring

The synthetic data generator (deterministic, seed=42) embedded one fraud ring among 200 normal claims:

- 8 people, all in Koramangala, Bangalore
- 3 share phone number A, 2 share phone number B, 5 share the same address
- All claims routed to "RapidFix Auto Hub" (garage) and "MedCare Wellness Clinic" (hospital)
- All handled by the same agent
- All filed within a 5-day window
- All describe "Multi-vehicle collision at junction"
- Repair amounts: ₹65K-180K (vs normal ₹5K-120K), medical: ₹15K-45K

The agent found all of this from flat CSVs in under 5 seconds.

## Total Exposure

₹39.8 lakhs identified. From 4 CSV files → 617 nodes → 15 anomalies → 4 hypotheses → 1 case file.

## What's Under the Hood

The `src/trident_engine/` package contains the production infrastructure: three-plane context separation, token budget enforcement (24,600 cap), cognitive entropy scoring, loss-aware compression, deterministic FSM (LLM proposes, FSM authorizes), forward/backward provenance tracing, and SRE-grade reliability monitoring. 93 tests cover both the agent and the engine.

## Next Steps

- Replace synthetic data with real anonymized claims
- Add FastAPI + WebSocket for live graph visualization (D3/Cytoscape)
- Add file watcher mode (watchdog) for drop-folder trigger
- Swap domain pack: same agent, different CSV schema = AML, vendor risk, cyber
