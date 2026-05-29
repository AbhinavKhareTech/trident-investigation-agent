#!/usr/bin/env python3
"""Trident Autonomous Investigation Agent — Demo Entrypoint.

Drop CSV files into a folder and watch the agent:
1. Ingest data → build graph
2. Detect anomalies → multi-signal analysis
3. Generate hypotheses → gather evidence
4. Create case file → recommend actions

Usage:
    # Generate synthetic data + run investigation
    python -m demo.investigation_agent.orchestrator

    # Watch a folder for new data
    python -m demo.investigation_agent.orchestrator --watch ./incoming_data

    # Use existing data
    python -m demo.investigation_agent.orchestrator --data ./my_data
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
from rich.table import Table
from rich.text import Text
from rich.tree import Tree
from rich import box

from demo.investigation_agent.models import Severity, InvestigationPhase
from demo.investigation_agent.synthetic.generator import generate_dataset
from demo.investigation_agent.graph_builder import InvestigationGraph
from demo.investigation_agent.detector import AnomalyDetector
from demo.investigation_agent.investigator import Investigator
from demo.investigation_agent.reporter import Reporter

console = Console()

SEVERITY_COLORS = {
    Severity.LOW: "green",
    Severity.MEDIUM: "yellow",
    Severity.HIGH: "dark_orange",
    Severity.CRITICAL: "red bold",
}

SEVERITY_EMOJI = {
    Severity.LOW: "🟢",
    Severity.MEDIUM: "🟡",
    Severity.HIGH: "🟠",
    Severity.CRITICAL: "🔴",
}

PHASE_EMOJI = {
    InvestigationPhase.OBSERVE: "👁️ ",
    InvestigationPhase.DETECT: "🔍",
    InvestigationPhase.HYPOTHESIZE: "🧠",
    InvestigationPhase.INVESTIGATE: "🔬",
    InvestigationPhase.COLLECT_EVIDENCE: "📎",
    InvestigationPhase.ASSESS_CONFIDENCE: "📊",
    InvestigationPhase.RECOMMEND_ACTION: "⚡",
    InvestigationPhase.CREATE_AUDIT_TRAIL: "📋",
}


def print_banner() -> None:
    banner = """
╔══════════════════════════════════════════════════════════════╗
║                                                              ║
║   ████████╗██████╗ ██╗██████╗ ███████╗███╗   ██╗████████╗   ║
║   ╚══██╔══╝██╔══██╗██║██╔══██╗██╔════╝████╗  ██║╚══██╔══╝   ║
║      ██║   ██████╔╝██║██║  ██║█████╗  ██╔██╗ ██║   ██║      ║
║      ██║   ██╔══██╗██║██║  ██║██╔══╝  ██║╚██╗██║   ██║      ║
║      ██║   ██║  ██║██║██████╔╝███████╗██║ ╚████║   ██║      ║
║      ╚═╝   ╚═╝  ╚═╝╚═╝╚═════╝ ╚══════╝╚═╝  ╚═══╝   ╚═╝      ║
║                                                              ║
║          AUTONOMOUS  INVESTIGATION  AGENT  v1.0              ║
║                                                              ║
║          AhinsaAI / Meraki Labs                              ║
╚══════════════════════════════════════════════════════════════╝
"""
    console.print(banner, style="bold cyan")


def phase_log(phase: InvestigationPhase, message: str, severity: Severity = Severity.LOW) -> None:
    emoji = PHASE_EMOJI.get(phase, "▶️")
    color = SEVERITY_COLORS.get(severity, "white")
    sev_emoji = SEVERITY_EMOJI.get(severity, "")
    console.print(f"  {emoji} [bold]{phase.value:25s}[/bold] │ [{color}]{sev_emoji} {message}[/{color}]")


def run_investigation(data_dir: str, output_dir: str = "./output") -> None:
    """Run the full autonomous investigation pipeline."""

    print_banner()
    console.print()

    # ═══════════════════════════════════════════════════════════
    # PHASE 1: OBSERVE — Detect new data
    # ═══════════════════════════════════════════════════════════
    console.rule("[bold cyan]PHASE 1: OBSERVE — Data Detection[/bold cyan]")
    console.print()

    files = {}
    for name in ["customers.csv", "claims.csv", "payments.csv", "agents.csv"]:
        path = os.path.join(data_dir, name)
        if os.path.exists(path):
            size = os.path.getsize(path)
            files[name] = path
            phase_log(InvestigationPhase.OBSERVE, f"Found: {name} ({size:,} bytes)")
        else:
            phase_log(InvestigationPhase.OBSERVE, f"Missing: {name}", Severity.MEDIUM)

    if not files:
        console.print("[red bold]  No data files found. Aborting.[/red bold]")
        return

    time.sleep(0.5)  # Dramatic pause
    console.print()

    # ═══════════════════════════════════════════════════════════
    # PHASE 2: INGEST — Build graph
    # ═══════════════════════════════════════════════════════════
    console.rule("[bold cyan]PHASE 2: INGEST — Graph Construction[/bold cyan]")
    console.print()

    graph = InvestigationGraph()

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
    ) as progress:
        if "agents.csv" in files:
            task = progress.add_task("Ingesting agents...", total=1)
            n = graph.ingest_agents(files["agents.csv"])
            progress.update(task, completed=1, description=f"Agents: {n} loaded")

        if "customers.csv" in files:
            task = progress.add_task("Ingesting customers...", total=1)
            n = graph.ingest_customers(files["customers.csv"])
            progress.update(task, completed=1, description=f"Customers: {n} loaded")

        if "claims.csv" in files:
            task = progress.add_task("Ingesting claims...", total=1)
            n = graph.ingest_claims(files["claims.csv"])
            progress.update(task, completed=1, description=f"Claims: {n} loaded")

        if "payments.csv" in files:
            task = progress.add_task("Ingesting payments...", total=1)
            n = graph.ingest_payments(files["payments.csv"])
            progress.update(task, completed=1, description=f"Payments: {n} loaded")

        # Discover implicit relationships
        task = progress.add_task("Discovering hidden connections...", total=1)
        n_implicit = graph.discover_implicit_relationships()
        progress.update(task, completed=1, description=f"Hidden connections: {n_implicit} found")

    console.print()

    # Graph stats
    stats_table = Table(title="📊 Graph Summary", box=box.ROUNDED, show_header=True, header_style="bold cyan")
    stats_table.add_column("Metric", style="bold")
    stats_table.add_column("Value", justify="right", style="green")
    stats_table.add_row("Total Nodes", f"{graph.node_count:,}")
    stats_table.add_row("Total Edges", f"{graph.edge_count:,}")
    stats_table.add_row("Implicit Connections", f"{n_implicit:,}")
    console.print(stats_table)
    console.print()

    time.sleep(0.8)

    # ═══════════════════════════════════════════════════════════
    # PHASE 3: DETECT — Anomaly Detection
    # ═══════════════════════════════════════════════════════════
    console.rule("[bold cyan]PHASE 3: DETECT — Anomaly Analysis[/bold cyan]")
    console.print()

    detector = AnomalyDetector()

    phase_log(InvestigationPhase.DETECT, "Running community detection...")
    time.sleep(0.3)
    phase_log(InvestigationPhase.DETECT, "Analyzing shared identities...")
    time.sleep(0.3)
    phase_log(InvestigationPhase.DETECT, "Checking amount distributions...")
    time.sleep(0.3)
    phase_log(InvestigationPhase.DETECT, "Scanning provider concentration...")
    time.sleep(0.3)
    phase_log(InvestigationPhase.DETECT, "Detecting temporal bursts...")
    time.sleep(0.3)

    anomalies = detector.detect_all(graph)

    console.print()
    phase_log(
        InvestigationPhase.DETECT,
        f"Detected {len(anomalies)} anomalies",
        Severity.HIGH if anomalies else Severity.LOW,
    )
    console.print()

    if anomalies:
        anomaly_table = Table(
            title="🔍 Detected Anomalies",
            box=box.ROUNDED,
            show_header=True,
            header_style="bold red",
        )
        anomaly_table.add_column("#", style="dim", width=3)
        anomaly_table.add_column("Type", width=22)
        anomaly_table.add_column("Severity", width=10)
        anomaly_table.add_column("Confidence", width=10, justify="right")
        anomaly_table.add_column("Description", max_width=55)

        for i, a in enumerate(anomalies[:10], 1):
            sev_color = SEVERITY_COLORS.get(a.severity, "white")
            sev_emoji = SEVERITY_EMOJI.get(a.severity, "")
            desc = a.description[:55] + "..." if len(a.description) > 55 else a.description
            anomaly_table.add_row(
                str(i),
                a.anomaly_type,
                f"[{sev_color}]{sev_emoji} {a.severity.value}[/{sev_color}]",
                f"{a.confidence:.0%}",
                desc,
            )
        if len(anomalies) > 10:
            anomaly_table.add_row("...", "", "", "", f"+{len(anomalies) - 10} more")

        console.print(anomaly_table)
        console.print()

    if not anomalies:
        console.print("[green]  No anomalies detected. Data appears clean.[/green]")
        return

    time.sleep(0.8)

    # ═══════════════════════════════════════════════════════════
    # PHASE 4: INVESTIGATE — Hypothesis Generation
    # ═══════════════════════════════════════════════════════════
    console.rule("[bold cyan]PHASE 4: INVESTIGATE — Hypothesis Generation[/bold cyan]")
    console.print()

    investigator = Investigator()

    phase_log(InvestigationPhase.HYPOTHESIZE, "Generating hypotheses from anomaly patterns...")
    time.sleep(0.4)
    phase_log(InvestigationPhase.COLLECT_EVIDENCE, "Gathering supporting evidence from graph...")
    time.sleep(0.4)
    phase_log(InvestigationPhase.COLLECT_EVIDENCE, "Checking for contradicting evidence...")
    time.sleep(0.3)
    phase_log(InvestigationPhase.ASSESS_CONFIDENCE, "Assessing confidence levels...")
    time.sleep(0.3)

    case = investigator.investigate(anomalies, graph)

    console.print()

    # Show hypotheses
    for i, hyp in enumerate(case.hypotheses, 1):
        status_icon = "✅" if hyp.status == "supported" else "⚠️"
        console.print(Panel(
            f"[bold]{hyp.title}[/bold]\n\n"
            f"{hyp.description}\n\n"
            f"Confidence: [bold]{hyp.confidence:.0%}[/bold] │ "
            f"Supporting evidence: {len(hyp.supporting_evidence)} │ "
            f"Contradicting: {len(hyp.contradicting_evidence)}\n"
            f"Status: {status_icon} {hyp.status}",
            title=f"Hypothesis #{i}",
            border_style="red" if hyp.confidence > 0.7 else "yellow",
        ))

    time.sleep(0.5)

    # ═══════════════════════════════════════════════════════════
    # PHASE 5: RECOMMEND — Actions
    # ═══════════════════════════════════════════════════════════
    console.rule("[bold cyan]PHASE 5: RECOMMEND — Autonomous Actions[/bold cyan]")
    console.print()

    for action in case.recommended_actions:
        prefix = action.split(":")[0] if ":" in action else ""
        icon = {
            "IMMEDIATE": "🔴", "FREEZE": "🧊", "ESCALATE": "🟠", "HOLD": "⏸️",
            "MONITOR": "👁️", "INVESTIGATE": "🔍", "AUDIT": "📋", "DOCUMENT": "📄",
        }.get(prefix, "▶️")
        severity = Severity.CRITICAL if prefix in ("IMMEDIATE", "FREEZE") else Severity.HIGH
        phase_log(InvestigationPhase.RECOMMEND_ACTION, f"{icon} {action}", severity)
        time.sleep(0.2)

    console.print()

    # ═══════════════════════════════════════════════════════════
    # PHASE 6: REPORT — Case File Generation
    # ═══════════════════════════════════════════════════════════
    console.rule("[bold cyan]PHASE 6: REPORT — Case File Generation[/bold cyan]")
    console.print()

    reporter = Reporter()
    filepath = reporter.generate(case, graph, output_dir)

    phase_log(InvestigationPhase.CREATE_AUDIT_TRAIL, f"Case file generated: {filepath}")
    console.print()

    # Final summary
    summary = Table(
        title="🎯 Investigation Complete",
        box=box.DOUBLE,
        show_header=False,
        title_style="bold green",
    )
    summary.add_column("", style="bold", width=25)
    summary.add_column("", style="green")
    summary.add_row("Case ID", case.case_id)
    summary.add_row("Severity", f"{SEVERITY_EMOJI.get(case.severity, '')} {case.severity.value}")
    summary.add_row("Confidence", f"{case.confidence:.0%}")
    summary.add_row("Hypotheses", str(len(case.hypotheses)))
    summary.add_row("Anomalies", str(len(case.anomalies)))
    summary.add_row("Entities Flagged", str(len(case.entity_ids)))
    summary.add_row("Actions", str(len(case.recommended_actions)))
    summary.add_row("Report", filepath)

    console.print(summary)
    console.print()

    # Money line
    total_exposure = sum(a.evidence.get("total_amount", 0) for a in case.anomalies)
    if total_exposure > 0:
        console.print(Panel(
            f"[bold white]Total exposure identified: [bold green]₹{total_exposure:,.0f}[/bold green]\n"
            f"From messy CSVs to investigation case file in [bold cyan]{len(files)} files → "
            f"{graph.node_count} nodes → {len(anomalies)} anomalies → "
            f"{len(case.hypotheses)} hypotheses → 1 case file[/bold cyan]",
            title="💰 ROI",
            border_style="green",
        ))

    console.print()
    return case


def main() -> None:
    parser = argparse.ArgumentParser(description="Trident Autonomous Investigation Agent")
    parser.add_argument("--data", type=str, default=None, help="Path to data directory with CSVs")
    parser.add_argument("--output", type=str, default="./output", help="Output directory for reports")
    parser.add_argument("--generate", action="store_true", help="Generate synthetic data first")
    parser.add_argument("--n-normal", type=int, default=200, help="Number of normal claims to generate")
    parser.add_argument("--ring-size", type=int, default=8, help="Size of embedded fraud ring")
    args = parser.parse_args()

    data_dir = args.data

    if args.generate or data_dir is None:
        console.print("[bold cyan]Generating synthetic dataset...[/bold cyan]")
        data_dir = "./incoming_data"
        files = generate_dataset(
            output_dir=data_dir,
            n_normal=args.n_normal,
            ring_size=args.ring_size,
        )
        for name, path in files.items():
            console.print(f"  📁 {name}: {path}")
        console.print()

    run_investigation(data_dir, args.output)


if __name__ == "__main__":
    main()
