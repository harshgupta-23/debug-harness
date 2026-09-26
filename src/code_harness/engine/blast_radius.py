"""Blast-radius engine and cross-boundary reachability analysis.

Enforces Invariant I3 & §4.2, §4.3:
- Computes upstream and downstream reachability paths.
- Detects cross-boundary dependents (DB ↔ Backend ↔ Frontend).
- Enforces the Fan-Out safety policy (MANDATORY_BUNDLE vs BACKWARD_COMPAT_SHIM_REQUIRED).
"""

from __future__ import annotations

from collections import deque
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
from pydantic import BaseModel, Field

from code_harness.core.graph import CodeGraph, EdgeKind, GraphNode, NodeKind


class SafetyPolicy(str, Enum):
    MANDATORY_BUNDLE = "MANDATORY_BUNDLE"
    BACKWARD_COMPAT_SHIM_REQUIRED = "BACKWARD_COMPAT_SHIM_REQUIRED"


class CrossBoundaryDependent(BaseModel):
    kind: str  # "frontendFetcher", "dbMigrationRisk", "apiEndpoint", "ormModel"
    node: GraphNode
    path: List[str] = Field(default_factory=list)


class BlastRadiusReport(BaseModel):
    graph_epoch: int
    target_node: str
    direct_dependents: int
    transitive_dependents: int
    cross_boundary_dependents: List[CrossBoundaryDependent] = Field(default_factory=list)
    affected_nodes: List[GraphNode] = Field(default_factory=list)
    policy: SafetyPolicy


class BlastRadiusEngine:
    """Computes reachability and enforces fan-out safety policies."""

    def __init__(self, max_fanout_threshold: int = 20) -> None:
        self.max_fanout_threshold = max_fanout_threshold

    def compute_blast_radius(
        self,
        graph: CodeGraph,
        target_node_id: str,
        max_depth: int = 10,
    ) -> BlastRadiusReport:
        """Compute full blast-radius downstream and cross-boundary from target node."""
        target_node = graph.get_node(target_node_id)
        if not target_node:
            raise KeyError(f"Node '{target_node_id}' not found in graph.")

        visited: Set[str] = {target_node_id}
        direct_dependents: Set[str] = set()
        transitive_dependents: Set[str] = set()
        cross_boundary: List[CrossBoundaryDependent] = []
        affected_nodes_map: Dict[str, GraphNode] = {}

        # Queue contains (node_id, current_depth, path)
        queue: deque[Tuple[str, int, List[str]]] = deque([(target_node_id, 0, [target_node_id])])

        while queue:
            curr_id, depth, path = queue.popleft()
            if depth >= max_depth:
                continue

            curr_node = graph.get_node(curr_id)
            if not curr_node:
                continue

            # Look for downstream edges (successors) and callers (predecessors via Calls)
            # In a code graph, callers of function F depend on F (predecessor in Calls edge)
            dependents: List[Tuple[GraphNode, str, str]] = []

            # 1. Predecessors via Calls or ConsumesRoute
            for pred_node, edge in graph.predecessors(curr_id):
                if edge.kind in {EdgeKind.CALLS, EdgeKind.CONSUMES_ROUTE, EdgeKind.READS_COLUMN}:
                    dependents.append((pred_node, edge.kind.value, "upstream_dependent"))

            # 2. Successors via ExposesEndpoint, MigratesTo, SerializesAs, ReadsColumn, WritesColumn
            for succ_node, edge in graph.successors(curr_id):
                if edge.kind in {
                    EdgeKind.EXPOSES_ENDPOINT,
                    EdgeKind.MIGRATES_TO,
                    EdgeKind.SERIALIZES_AS,
                    EdgeKind.READS_COLUMN,
                    EdgeKind.WRITES_COLUMN,
                }:
                    dependents.append((succ_node, edge.kind.value, "downstream_dependent"))

            # 3. If curr_node is an Endpoint, any frontend fetcher consuming it is a dependent
            if curr_node.kind == NodeKind.ENDPOINT:
                for pred_node, edge in graph.predecessors(curr_id):
                    if edge.kind == EdgeKind.CONSUMES_ROUTE:
                        dependents.append((pred_node, "ConsumesRoute", "frontendFetcher"))

            for dep_node, edge_kind_val, dep_role in dependents:
                if dep_node.id in visited:
                    continue
                visited.add(dep_node.id)
                new_path = path + [dep_node.id]

                if depth == 0:
                    direct_dependents.add(dep_node.id)
                else:
                    transitive_dependents.add(dep_node.id)

                affected_nodes_map[dep_node.id] = dep_node

                # Check cross-boundary kinds
                if dep_node.file_path.endswith((".js", ".ts", ".jsx", ".tsx")) or dep_node.kind == NodeKind.FUNCTION and dep_node.origin_language == "javascript":
                    cross_boundary.append(
                        CrossBoundaryDependent(
                            kind="frontendFetcher",
                            node=dep_node,
                            path=new_path,
                        )
                    )
                elif dep_node.kind == NodeKind.DB_COLUMN or dep_node.file_path.endswith(".sql"):
                    cross_boundary.append(
                        CrossBoundaryDependent(
                            kind="dbMigrationRisk",
                            node=dep_node,
                            path=new_path,
                        )
                    )
                elif dep_node.kind == NodeKind.ENDPOINT:
                    cross_boundary.append(
                        CrossBoundaryDependent(
                            kind="apiEndpoint",
                            node=dep_node,
                            path=new_path,
                        )
                    )

                queue.append((dep_node.id, depth + 1, new_path))

        total_dependents = len(direct_dependents) + len(transitive_dependents)
        policy = (
            SafetyPolicy.BACKWARD_COMPAT_SHIM_REQUIRED
            if total_dependents > self.max_fanout_threshold
            else SafetyPolicy.MANDATORY_BUNDLE
        )

        return BlastRadiusReport(
            graph_epoch=graph.graph_epoch,
            target_node=target_node_id,
            direct_dependents=len(direct_dependents),
            transitive_dependents=len(transitive_dependents),
            cross_boundary_dependents=cross_boundary,
            affected_nodes=list(affected_nodes_map.values()),
            policy=policy,
        )
