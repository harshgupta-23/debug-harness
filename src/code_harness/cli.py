"""Command-line interface for the Deterministic Code-Graph Harness."""

from __future__ import annotations

import time
from pathlib import Path
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from code_harness.core.graph import NodeKind
from code_harness.core.indexer import RepositoryIndexer
from code_harness.engine.blast_radius import BlastRadiusEngine
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
def step(
    repo: str = typer.Option(".", "--repo", "-r", help="Path to target project"),
    session_id: Optional[str] = typer.Option(None, "--session", "-s", help="Existing session ID"),
    issue: Optional[str] = typer.Option(None, "--issue", "-i", help="Issue description on start"),
    symptom: Optional[str] = typer.Option(None, "--symptom", help="Initial function anchor"),
    patch: Optional[str] = typer.Option(None, "--patch", "-p", help="Replacement code for 'curr' ONLY"),
    next_node: Optional[List[str]] = typer.Option(None, "--next", "-n", help="Neighbor node ID(s) to modify next"),
    apply: bool = typer.Option(True, "--apply/--no-apply", help="Apply to disk when all links finish"),
) -> None:
    """Step 1 node at a time through the code graph."""
    repo_path = Path(repo).resolve()
    harness = Harness(repo_path=repo_path)

    # Check if patch is file path
    patch_text = patch
    if patch and "\n" not in patch and len(patch) < 260:
        try:
            p = Path(patch)
            if p.exists() and p.is_file():
                patch_text = p.read_text(encoding="utf-8")
        except OSError:
            pass

    state = harness.step(
        session_id=session_id,
        issue=issue,
        symptom=symptom,
        curr_patch=patch_text,
        modify_next_nodes=next_node,
        apply=apply,
    )

    console.print(f"[bold cyan][*] Session ID:[/bold cyan] {state.session_id}")
    console.print(f"    Status: [bold]{state.verification_status}[/bold] (Done: {state.done})\n")

    if state.done:
        if state.verification_status == "SANDBOX_VERIFIED":
            console.print("[bold green][✓] All requested links resolved and verified in sandbox![/bold green]")
            if state.applied:
                console.print(f"    Committed edits to: {state.touched_files}")
        else:
            console.print(f"[bold red][✗] Session Finished with Status: {state.verification_status}[/bold red]")
            for d in state.diagnostics:
                console.print(f"    • {d}")
        return

    # Display curr
    if state.curr:
        curr = state.curr
        console.print(f"[bold green]▶ CURRENT FOCUS (Only this node can be modified):[/bold green]")
        console.print(f"  • Symbol: [bold]{curr.name}[/bold] ({curr.kind})")
        console.print(f"  • Location: {curr.file_path} (lines {curr.start_line}-{curr.end_line})")
        console.print(f"  • Node ID: {curr.node_id}")
        console.print(f"[dim]--- Exact AST Code Slice ---[/dim]\n{curr.code}\n[dim]----------------------------[/dim]\n")

    # Display 1-hop dependents
    if state.dependents_depth_1:
        table = Table(title="Depth-1 Dependents (1-hop Upstream & Downstream)")
        table.add_column("Direction", style="cyan")
        table.add_column("Relationship", style="magenta")
        table.add_column("Symbol", style="bold")
        table.add_column("File:Lines", style="dim")
        table.add_column("Node ID", style="yellow")

        for dep in state.dependents_depth_1:
            table.add_row(
                dep.direction or "",
                dep.relationship or "",
                dep.name,
                f"{dep.file_path}:{dep.start_line}-{dep.end_line}",
                dep.node_id,
            )
        console.print(table)

    if state.pending_queue:
        console.print(f"\n[yellow]Remaining Queued Nodes:[/yellow] {state.pending_queue}")


@app.command()
def mcp() -> None:
    """Run standard Model Context Protocol (MCP) stdio server for AGY."""
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
