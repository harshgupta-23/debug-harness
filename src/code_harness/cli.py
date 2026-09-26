"""Command-line interface for the Deterministic Code-Graph Harness."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from code_harness.core.graph import NodeKind
from code_harness.core.indexer import RepositoryIndexer
from code_harness.engine.blast_radius import BlastRadiusEngine
from code_harness.engine.system1 import System1Scorer
from code_harness.harness import Harness
from code_harness.integrations.mcp_server import run_stdio_mcp
from code_harness.integrations.proxy import run_proxy_server

app = typer.Typer(
    name="harness",
    help="Deterministic Code-Graph Debugging & Mutation Harness CLI",
    add_completion=False,
)
console = Console()


@app.command()
def fix(
    repo: str = typer.Option(".", "--repo", "-r", help="Path to project directory to fix"),
    issue: str = typer.Option(..., "--issue", "-i", help="Description of the bug or problem"),
    apply: bool = typer.Option(False, "--apply", "-a", help="Write verified patch to disk"),
    use_harness: bool = typer.Option(
        True,
        "--harness/--no-harness",
        help="Toggle deterministic graph parser & contract on or off",
    ),
    model: Optional[str] = typer.Option(None, "--model", "-m", help="Model name (e.g. gemini-1.5-flash, gpt-4o)"),
    symptom: Optional[str] = typer.Option(None, "--symptom", "-s", help="Optional symptom node or file:line"),
) -> None:
    """Analyze issue, call LLM with scoped ContextStack, verify via sandbox, and apply."""
    repo_path = Path(repo).resolve()
    mode_label = "Harness (Deterministic Graph)" if use_harness else "Baseline (Raw Context)"
    console.print(f"[bold cyan][*] Running Fix on:[/bold cyan] {repo_path}")
    console.print(f"    Mode: [bold yellow]{mode_label}[/bold yellow]")
    console.print(f"    Issue: {issue}\n")

    harness = Harness(repo_path=repo_path, use_harness=use_harness, model=model)
    result = harness.fix(issue=issue, apply=apply, symptom_node=symptom)

    # Output status
    if result.success:
        console.print(f"[bold green][✓] Fix Verified Successfully! Status: {result.verification_status}[/bold green]")
    else:
        console.print(f"[bold yellow][!] Status: {result.verification_status}[/bold yellow]")

    if result.applied:
        console.print(f"[bold green]    Edits committed to disk for {len(result.touched_files)} files.[/bold green]")
    elif result.success and not apply:
        console.print("    (Run with --apply to commit verified patch to disk)")

    # Telemetry summary
    table = Table(title="Execution Telemetry")
    table.add_column("Parameter", style="cyan")
    table.add_column("Value", style="magenta")
    table.add_row("LLM API Calls", str(result.metrics.llm_api_calls))
    table.add_row("Input Tokens", f"{result.metrics.input_tokens:,}")
    table.add_row("Output Tokens", f"{result.metrics.output_tokens:,}")
    table.add_row("Total Tokens", f"{result.metrics.total_tokens:,}")
    table.add_row("Execution Time", f"{result.metrics.wall_clock_seconds:.2f}s")
    table.add_row("Verification Gate", result.verification_status)
    if result.metrics.total_atomic_dependents > 0:
        table.add_row("Locked Dependents", f"{result.metrics.atomic_dependents_locked} / {result.metrics.total_atomic_dependents}")
    console.print(table)

    if result.diagnostics:
        console.print("\n[bold]Diagnostics / Logs:[/bold]")
        for d in result.diagnostics:
            console.print(f"  • {d}")


@app.command()
def mcp() -> None:
    """Run standard Model Context Protocol (MCP) stdio server for AGY, Cursor, Claude."""
    run_stdio_mcp()


@app.command()
def index(
    repo: str = typer.Option(".", "--repo", "-r", help="Path to repository to index"),
) -> None:
    """Deterministically index repository files into typed code graph."""
    repo_path = Path(repo).resolve()
    console.print(f"[bold cyan][*] Indexing repository:[/bold cyan] {repo_path}")

    start = time.perf_counter()
    indexer = RepositoryIndexer(repo_path)
    graph = indexer.index()
    elapsed = time.perf_counter() - start

    console.print(f"[bold green][✓] Indexing completed in {elapsed:.2f}s[/bold green]")
    console.print(f"  • Graph Epoch: {graph.graph_epoch}")
    console.print(f"  • Nodes: {graph.node_count()}")
    console.print(f"  • Edges: {graph.edge_count()}")
    console.print(f"  • Unresolved References: {graph.unresolved_refs}")

    table = Table(title="Indexed Node Breakdown")
    table.add_column("Node Kind", style="cyan")
    table.add_column("Count", justify="right")
    for kind in NodeKind:
        count = len(graph.find_nodes_by_kind(kind))
        if count > 0:
            table.add_row(kind.value, str(count))
    console.print(table)


@app.command()
def trace(
    symptom: str = typer.Option(..., "--symptom", "-s", help="Symptom node ID or file:line"),
    repo: str = typer.Option(".", "--repo", "-r", help="Path to repository"),
    query: str = typer.Option("exception error", "--query", "-q", help="Error text or query"),
) -> None:
    """Trace root cause using bounded graph traversal and System-1 edge scoring."""
    repo_path = Path(repo).resolve()
    indexer = RepositoryIndexer(repo_path)
    graph = indexer.index()
    scorer = System1Scorer()

    target_node = graph.get_node(symptom)
    if not target_node and ":" in symptom:
        parts = symptom.split(":")
        try:
            line_no = int(parts[1])
            target_node = graph.find_node_by_span(parts[0], line_no)
        except Exception:
            pass

    if not target_node:
        all_fns = graph.find_nodes_by_kind(NodeKind.FUNCTION)
        target_node = all_fns[0] if all_fns else None

    if not target_node:
        console.print("[red][✗] Error: Could not resolve symptom node in graph.[/red]")
        raise typer.Exit(code=1)

    candidates = []
    for pred, edge in graph.predecessors(target_node.id):
        candidates.append((pred, edge, [target_node.id]))
    for succ, edge in graph.successors(target_node.id):
        candidates.append((succ, edge, [target_node.id]))

    ranked = scorer.score_candidates(query, candidates)

    table = Table(title=f"Root-Cause Candidates (Epoch {graph.graph_epoch})")
    table.add_column("Rank", justify="center")
    table.add_column("Node ID", style="bold")
    table.add_column("Edge Kind", style="cyan")
    table.add_column("Calibrated Score", justify="right", style="green")
    for i, c in enumerate(ranked[:5], 1):
        edge_name = c.edge.kind.value if c.edge else "Direct"
        table.add_row(str(i), c.node.id, edge_name, f"{c.calibrated_score:.4f}")
    console.print(table)


@app.command(name="blast-radius")
def blast_radius_cmd(
    node: str = typer.Option(..., "--node", "-n", help="Target node ID"),
    repo: str = typer.Option(".", "--repo", "-r", help="Path to repository"),
) -> None:
    """Compute reachability paths and check Fan-Out safety policy."""
    repo_path = Path(repo).resolve()
    indexer = RepositoryIndexer(repo_path)
    graph = indexer.index()
    engine = BlastRadiusEngine()

    if not graph.has_node(node):
        console.print(f"[red][✗] Node '{node}' not found in graph.[/red]")
        raise typer.Exit(code=1)

    report = engine.compute_blast_radius(graph, node)
    console.print(f"[bold cyan][*] Blast Radius Analysis for:[/bold cyan] {node}")
    console.print(f"  • Direct Dependents: {report.direct_dependents}")
    console.print(f"  • Transitive Dependents: {report.transitive_dependents}")
    console.print(f"  • Safety Policy: [bold yellow]{report.policy.value}[/bold yellow]")
    console.print(f"  • Cross-Boundary Dependents: {len(report.cross_boundary_dependents)}")


@app.command()
def serve(
    port: int = typer.Option(8000, "--port", "-p", help="HTTP / MCP port"),
    repo: str = typer.Option(".", "--repo", "-r", help="Repository path"),
) -> None:
    """Start local MCP server and OpenAI proxy for external agent tools."""
    run_proxy_server(port=port, repo_path=repo)


if __name__ == "__main__":
    app()
