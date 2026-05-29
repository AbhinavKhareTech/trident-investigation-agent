"""Case file reporter — generates markdown investigation reports.

The deliverable: a complete investigation case file with evidence,
hypotheses, recommendations, and audit trail.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any

from demo.investigation_agent.models import CaseFile, Severity
from demo.investigation_agent.graph_builder import InvestigationGraph


class Reporter:
    """Generates investigation case files in Markdown."""

    def generate(
        self,
        case: CaseFile,
        graph: InvestigationGraph,
        output_dir: str = "./output",
    ) -> str:
        """Generate a markdown case file and save to disk.

        Returns the file path.
        """
        os.makedirs(output_dir, exist_ok=True)

        md = self._render_markdown(case, graph)

        filepath = os.path.join(output_dir, f"{case.case_id}_report.md")
        with open(filepath, "w") as f:
            f.write(md)

        return filepath

    def _render_markdown(self, case: CaseFile, graph: InvestigationGraph) -> str:
        severity_emoji = {
            Severity.LOW: "🟢",
            Severity.MEDIUM: "🟡",
            Severity.HIGH: "🟠",
            Severity.CRITICAL: "🔴",
        }

        lines = []
        lines.append(f"# {severity_emoji.get(case.severity, '⚪')} Investigation Report: {case.title}")
        lines.append("")
        lines.append(f"**Case ID:** {case.case_id}")
        lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append(f"**Severity:** {case.severity.value}")
        lines.append(f"**Confidence:** {case.confidence:.0%}")
        lines.append(f"**Entities Involved:** {len(case.entity_ids)}")
        lines.append("")
        lines.append("---")
        lines.append("")

        # Executive Summary
        lines.append("## Executive Summary")
        lines.append("")
        lines.append(case.summary)
        lines.append("")

        # Hypotheses
        if case.hypotheses:
            lines.append("## Investigation Hypotheses")
            lines.append("")
            for i, hyp in enumerate(case.hypotheses, 1):
                status_icon = "✅" if hyp.status == "supported" else "⚠️" if hyp.status == "inconclusive" else "❌"
                lines.append(f"### {i}. {hyp.title} {status_icon}")
                lines.append(f"**Confidence:** {hyp.confidence:.0%} | **Status:** {hyp.status}")
                lines.append("")
                lines.append(hyp.description)
                lines.append("")

                if hyp.supporting_evidence:
                    lines.append("**Supporting Evidence:**")
                    for ev in hyp.supporting_evidence:
                        lines.append(f"- {ev['description']}")
                    lines.append("")

                if hyp.contradicting_evidence:
                    lines.append("**Contradicting Evidence:**")
                    for ev in hyp.contradicting_evidence:
                        lines.append(f"- {ev['description']}")
                    lines.append("")

        # Anomalies
        if case.anomalies:
            lines.append("## Detected Anomalies")
            lines.append("")
            lines.append("| # | Type | Severity | Confidence | Description |")
            lines.append("|---|------|----------|------------|-------------|")
            for i, a in enumerate(case.anomalies, 1):
                desc = a.description[:80] + "..." if len(a.description) > 80 else a.description
                lines.append(
                    f"| {i} | {a.anomaly_type} | {severity_emoji.get(a.severity, '')} {a.severity.value} "
                    f"| {a.confidence:.0%} | {desc} |"
                )
            lines.append("")

        # Entities of Interest
        if case.entity_ids:
            lines.append("## Entities of Interest")
            lines.append("")
            lines.append("| Entity ID | Type | Name | Risk Score |")
            lines.append("|-----------|------|------|------------|")
            for eid in case.entity_ids[:20]:  # Top 20
                entity = graph.get_entity(eid)
                if entity:
                    lines.append(
                        f"| {entity.id} | {entity.entity_type} | {entity.name} | {entity.risk_score:.2f} |"
                    )
            if len(case.entity_ids) > 20:
                lines.append(f"| ... | | {len(case.entity_ids) - 20} more entities | |")
            lines.append("")

        # Recommended Actions
        if case.recommended_actions:
            lines.append("## Recommended Actions")
            lines.append("")
            for action in case.recommended_actions:
                prefix = action.split(":")[0] if ":" in action else ""
                icon = {"IMMEDIATE": "🔴", "FREEZE": "🧊", "ESCALATE": "🟠", "HOLD": "⏸️",
                        "MONITOR": "👁️", "INVESTIGATE": "🔍", "AUDIT": "📋", "DOCUMENT": "📄"}.get(prefix, "▶️")
                lines.append(f"- {icon} {action}")
            lines.append("")

        # Graph Statistics
        lines.append("## Graph Statistics")
        lines.append("")
        lines.append(f"- **Total nodes:** {graph.node_count}")
        lines.append(f"- **Total edges:** {graph.edge_count}")
        lines.append(f"- **Entities in case:** {len(case.entity_ids)}")
        lines.append("")

        # Audit Trail
        lines.append("## Audit Trail")
        lines.append("")
        lines.append("This report was generated autonomously by the Trident Investigation Agent.")
        lines.append("All anomalies, hypotheses, and recommendations are based on graph analysis")
        lines.append("of the ingested data. No external data sources were consulted.")
        lines.append("")
        lines.append(f"- **Agent:** Trident Autonomous Investigator v1.0")
        lines.append(f"- **Report generated:** {datetime.now().isoformat()}")
        lines.append(f"- **Data integrity:** All source CSVs hashed at ingestion")
        lines.append(f"- **Governance:** Human review required before action execution")
        lines.append("")
        lines.append("---")
        lines.append("*Generated by BGI Trident — AhinsaAI / Meraki Labs*")

        return "\n".join(lines)
