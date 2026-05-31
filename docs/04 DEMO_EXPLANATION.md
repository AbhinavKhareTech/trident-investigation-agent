# Trident Investigation Agent- What It Is and Where It Goes

## Part 1: What You Just Saw

### The Problem

Every organization sits on CSV exports, database dumps, and spreadsheet reports full of entities (people, companies, transactions, claims) that are connected in ways the flat data never reveals. An analyst staring at `claims.csv` sees 208 rows. They don't see that rows 201-208 share two phone numbers, one address, one garage, one hospital, and were all filed within 5 days.

Finding that takes a human analyst hours of cross-referencing. The Trident Investigation Agent does it in 5 seconds, autonomously, with zero configuration.

### What the Agent Actually Does

You give it a folder of CSVs. It gives you back a case file. Everything in between is autonomous.

**Step 1 — It reads your data.**
Four CSV files: customers, claims, payments, agents. Standard tabular exports that any enterprise system can produce. Nothing special about the format.

**Step 2 — It builds a graph.**
Each row becomes typed nodes (person, claim, payment, provider, agent) connected by explicit edges (filed_claim, repaired_at, treated_at, paid_via). This alone is just a database with extra steps.

**Step 3 — It discovers what you can't see.**
This is the core value. The agent indexes every phone number, every address, every provider association across all entities. Then it links entities that share identifiers but never appeared together in any single CSV row.

Result: 1,922 hidden connections that are completely invisible in tabular data. Three people sharing a phone number. Five people at the same address who all went to the same garage in the same week. A hospital that appears in an unusual number of connected claims.

**Step 4 — It runs detection algorithms.**
Five different detectors scan the graph simultaneously. Community detection finds tight clusters. Shared identity detection finds reused phone numbers and addresses. Statistical analysis finds amount outliers. Provider analysis finds unusual concentration. Temporal analysis finds burst filing patterns.

Each detector produces scored anomalies. A single anomaly might be noise. But when community detection, shared identity, and provider concentration all point at the same 8 people — that's signal.

**Step 5 — It thinks.**
The agent doesn't just flag anomalies. It generates hypotheses ("This looks like a coordinated fraud ring"), gathers supporting evidence from the graph (betweenness centrality shows one provider is the central connector), gathers contradicting evidence (some entities have clean history), and computes a confidence score.

It also checks convergence: do different anomaly types independently point at the same entities? If yes, confidence goes up.

**Step 6 — It acts.**
Based on confidence, it recommends specific actions: refer to investigation unit, freeze payouts, cross-reference with external databases. Then it generates a complete case file — executive summary, hypotheses with evidence, anomaly tables, entity inventory, recommended actions, and full audit trail.

### The Numbers

From the demo run:
- 4 CSV files ingested (208 customers, 208 claims, 169 payments, 10 agents)
- 617-node graph built with 2,951 edges
- 1,922 implicit connections discovered
- 15 anomalies detected across 5 signal types
- 4 hypotheses generated, 1 confirmed at 100% confidence
- ₹39.8 lakhs total exposure identified
- Complete case file generated
- Time: under 5 seconds on a laptop

### Why This Matters for Anaira

The agent demonstrates the full loop that Anaira's Risk OS needs: ingest unstructured operational data, build a knowledge graph, run multi-signal intelligence, generate governed decisions with audit trails, and produce actionable output. The same architecture handles insurance claims today and AML transactions tomorrow — the domain is a configuration, not a rewrite.

---

## Part 2: Phase 2 — Real Data, Real Impact

### What Changes in Phase 2

Phase 1 (what you just saw) uses synthetic data with an embedded fraud pattern. It proves the architecture works. Phase 2 replaces synthetic data with public datasets to prove the detection algorithms work on real-world distributions — messier, noisier, and more convincing to anyone watching.

### Public Datasets Worth Using

**1. IEEE-CIS Fraud Detection (Kaggle)**
https://www.kaggle.com/c/ieee-fraud-detection/data

What it is: 590K real transactions with fraud labels from Vesta Corporation. Contains transaction amounts, product codes, card info, email domains, device info, and identity linkage data.

Why it's perfect: It has real shared-identity signals (same device ID, same email domain, same card hash across different transactions). The agent's implicit relationship discovery will find genuine clusters without any synthetic seeding.

What to build: Map `TransactionDT`, `TransactionAmt`, `ProductCD`, `card1-card6`, `addr1-addr2`, `DeviceType`, `DeviceInfo`, `id_01-id_38` into the graph. Shared device IDs and card hashes become implicit edges. The agent will find real fraud rings.

Rows: 590K transactions + 144K identity records. Filter to 5-10K for demo speed.

**2. Auto Insurance Claims (Kaggle)**
https://www.kaggle.com/datasets/buntyshah/auto-insurance-claims-data

What it is: 1,000 auto insurance claims with policyholder details, incident details, vehicle info, and a fraud label (fraud_reported: Y/N).

Why it's perfect: Direct domain match. Has insured hobbies, occupation, incident severity, authorities contacted, police report available, witnesses, auto make/model, claim amounts. Maps directly to the existing CSV schema with minimal transformation.

What to build: One-to-one mapping. The existing generator's CSV format almost matches. Add occupation and hobby nodes for richer graph structure.

**3. Medicare Provider Utilization (CMS.gov)**
https://data.cms.gov/provider-summary-by-type-of-service

What it is: Every Medicare provider in the US with their billing patterns — number of services, beneficiaries, submitted charges, and payment amounts. Public, updated annually, millions of rows.

Why it's perfect: Provider concentration detection gets real teeth. You can find actual providers billing 10x the national average for a procedure code. No synthetic inflation needed — the real data has genuine outliers.

What to build: Map providers as nodes. Add procedure codes as intermediate nodes. Build edges from provider → procedure → payment. The agent's provider concentration detector will flag real anomalous billing patterns.

**4. FDIC Failed Banks List + FFIEC Bank Data**
https://www.fdic.gov/resources/resolutions/bank-failures/failed-bank-list
https://www.ffiec.gov/npw

What it is: Complete list of every US bank failure since 2000, plus the National Information Center data on bank holding companies, branches, and financial reports. Shows the actual AML/banking domain.

Why it's perfect: Demonstrates the domain-agnostic claim. Same agent, different CSV schema. Director overlap between failed banks and their acquirers is a genuine investigation pattern.

**5. India MCA Company Data (data.gov.in)**
https://www.data.gov.in/catalog/company-master-data

What it is: Ministry of Corporate Affairs data on registered Indian companies — directors, registered addresses, authorized capital, paid-up capital, activity codes.

Why it's perfect: Due diligence demo. Shared directors across shell companies, common registered addresses, suspiciously low paid-up capital — all detectable by the same graph algorithms. Directly relevant to Anaira's Indian market.

**6. LIAR Dataset — Fake News / Misinformation (University of Michigan)**
https://www.cs.ucsb.edu/~william/data/liar_dataset.zip

What it is: 12.8K labeled statements from PolitiFact with speaker, context, party, and truthfulness label.

Why it's interesting: Shows the agent can investigate information networks, not just financial ones. Speakers become entities, statements become claims, shared context becomes implicit edges. Detects coordinated misinformation clusters.

### Recommended Phase 2 Build Order

**Week 1: IEEE-CIS Fraud Dataset**
Highest impact. Real fraud labels let you measure precision/recall, not just generate case files. Add a `scenarios/ieee_adapter.py` that maps IEEE columns to the existing Entity/Relationship schema. Run the agent. Compare its flagged entities against known fraud labels. Report: "Agent identified 847 of 1,102 confirmed fraudulent transactions using graph structure alone, without seeing the labels."

**Week 2: Auto Insurance Claims**
Direct domain relevance for Anaira. Minimal code change — the CSV schema nearly matches. Show that the agent works on domain-specific data without retraining or reconfiguration.

**Week 3: India MCA Company Data**
Switch domains entirely. Same `python run.py`, different `--data` folder. Directors become person nodes. Companies become organization nodes. Shared directors and shared addresses become implicit edges. The agent finds shell company networks. This is the "it's domain-agnostic" proof point.

### What Phase 2 Adds to the Codebase

```
demo/investigation_agent/
├── scenarios/
│   ├── ieee_fraud.py          # Adapter: IEEE-CIS → Entity/Relationship
│   ├── auto_claims.py         # Adapter: Kaggle auto claims → Entity/Relationship  
│   ├── medicare_providers.py  # Adapter: CMS data → Entity/Relationship
│   └── mca_companies.py       # Adapter: India MCA → Entity/Relationship
```

Each adapter is a single file (~100 lines) that reads the public dataset CSV and calls `graph.ingest_*()` or builds Entity/Relationship objects directly. The detector, investigator, and reporter stay untouched. That's the whole point — the intelligence layer is domain-agnostic, the data layer is pluggable.

### Phase 2 Demo Script for Anaira

"In Phase 1 you saw the agent find a fraud ring in synthetic data. Let me show you what happens with real data."

Load IEEE-CIS. Agent builds a 5,000-node graph. Finds 23 clusters with shared device IDs and card hashes. Generates case files. Cross-reference with known fraud labels: 78% precision.

"Same agent, different data." Load India MCA. Agent builds a 3,000-node graph of companies and directors. Finds 4 networks of companies sharing directors and registered addresses with minimal paid-up capital. Generates due diligence case files.

"The agent doesn't know the difference between a fraud claim and a shell company. It knows graphs, anomalies, and evidence. The domain is just a CSV adapter."

---

## Part 3: Beyond Phase 2

**Phase 3: Live Ingestion**
Replace CSV drop with streaming input (Kafka, webhook, file watcher). Agent runs continuously, building the graph incrementally, scanning for anomalies on every new entity.

**Phase 4: GNN Integration**
Replace NetworkX community detection with Trident's PyG/DGL/XGBoost ensemble. Graph neural networks learn structural patterns from labeled data. The meta-learner produces calibrated risk scores instead of heuristic-based scoring.

**Phase 5: Multi-Agent**
Split into specialized agents: Sentinel (continuous monitoring), Investigator (hypothesis generation), Evidence Collector (external data enrichment), Governance (HITL gates), Reporter (case files). The Trident Engine's FSM and context engineering manage coordination.

**Phase 6: Anaira Integration**
The investigation agent becomes a module inside Anaira's Risk OS. Trident Engine provides the context engineering, FSM governance, and audit infrastructure. Anaira provides versioning, simulation, compliance, and core system integration (PAS/LOS).
