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
def prepare(
    repo: str = typer.Option(".", "--repo", "-r", help="Path to target project"),
    issue: str = typer.Option(..., "--issue", "-i", help="Error message or problem description"),
    symptom: Optional[str] = typer.Option(None, "--symptom", "-s", help="Optional symptom node or file:line"),
) -> None:
    """Phase 1: Deterministically lock cross-boundary dependents and print ContextStack."""
    repo_path = Path(repo).resolve()
    harness = Harness(repo_path=repo_path)
    prep = harness.prepare(issue=issue, symptom_node=symptom)

    console.print(f"[bold cyan][*] Plan Prepared:[/bold cyan] {prep.plan_id}")
    console.print(f"    Target: [bold]{prep.target_node}[/bold] in {prep.target_file}")
    console.print(f"    Estimated Tokens: {prep.estimated_tokens}")

    if prep.locked_dependents:
        table = Table(title="Locked Dependents (Mandatory Atomic Contract)")
        table.add_column("Kind", style="cyan")
        table.add_column("Node ID", style="bold")
        table.add_column("File", style="dim")
        for dep in prep.locked_dependents:
            table.add_row(dep.kind, dep.node_id, dep.file_path)
        console.print(table)

    console.print(f"\n[bold]=== Context Stack ===[/bold]\n{prep.context_stack}\n")
    console.print(f"[bold yellow]Instructions:[/bold yellow] {prep.instructions}")


@app.command()
def verify(
    repo: str = typer.Option(".", "--repo", "-r", help="Path to target project"),
    plan_id: str = typer.Option(..., "--plan-id", "-p", help="Plan ID from harness prepare"),
    patch: str = typer.Option(..., "--patch", help="Replacement code or file path containing patch"),
    apply: bool = typer.Option(True, "--apply/--no-apply", help="Commit verified diff to disk"),
) -> None:
    """Phase 2: Verify patch in sandbox and apply to disk."""
    repo_path = Path(repo).resolve()
    harness = Harness(repo_path=repo_path)

    # Check if patch argument is a file path
    patch_text = patch
    p = Path(patch)
    if p.exists() and p.is_file():
        patch_text = p.read_text(encoding="utf-8")

    res = harness.verify_and_apply(plan_id=plan_id, target_patch=patch_text, apply=apply)
    if res.passed:
        console.print(f"[bold green][✓] Sandbox Verification Passed! Status: {res.status}[/bold green]")
        if res.applied:
            console.print(f"    Applied changes to: {res.touched_files}")
    else:
        console.print(f"[bold red][✗] Verification Failed! Status: {res.status}[/bold red]")
        for d in res.diagnostics:
            console.print(f"    • {d}")


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
    symptom: Optional[str] = typer.Option(None, "--symptom", "-s", help="Optional symptom node or file:line"),
) -> None:
    """One-shot fix for terminal execution."""
    repo_path = Path(repo).resolve()
    mode_label = "Harness (Deterministic Graph)" if use_harness else "Baseline (Raw Context)"
    console.print(f"[bold cyan][*] Running Fix on:[/bold cyan] {repo_path}")
    console.print(f"    Mode: [bold yellow]{mode_label}[/bold yellow]")
    console.print(f"    Issue: {issue}\n")

    harness = Harness(repo_path=repo_path, use_harness=use_harness)
    result = harness.fix(issue=issue, apply=apply, symptom_node=symptom)

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
    table.add_row("Input Tokens", f"{result.metrics.input_tokens:,}")
    table.add_row("Output Tokens", f"{result.metrics.output_tokens:,}")
    table.add_row("Total Tokens", f"{result.metrics.total_tokens:,}")
    table.add_row("Execution Time", f"{result.metrics.wall_clock_seconds:.2f}s")
    table.add_row("Verification Gate", result.verification_status)
    console.print(table)


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
