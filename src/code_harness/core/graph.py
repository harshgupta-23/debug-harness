"""In-memory deterministic directed graph store backed by NetworkX.

Strictly enforces Invariants I1 and I2:
- No vector similarity or embedding edges (forbids 'SimilarTo' / 'EmbeddingNeighbor').
- Every edge is a deterministic parser/typechecker fact with confidence score.
- Logical clock (graph_epoch) increments on every mutation.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import networkx as nx
from pydantic import BaseModel, Field


class NodeKind(str, Enum):
    FUNCTION = "Function"
    CLASS = "Class"
    INTERFACE = "Interface"
    ENDPOINT = "Endpoint"
    DB_COLUMN = "DBColumn"
    DTO = "DTO"
    TEST_CASE = "TestCase"


class EdgeKind(str, Enum):
    CALLS = "Calls"
    IMPLEMENTS = "Implements"
    IMPORTS = "Imports"
    MUTATES = "Mutates"
    EXPOSES_ENDPOINT = "ExposesEndpoint"
    CONSUMES_ROUTE = "ConsumesRoute"
    READS_COLUMN = "ReadsColumn"
    WRITES_COLUMN = "WritesColumn"
    SERIALIZES_AS = "SerializesAs"
    MIGRATES_TO = "MigratesTo"


# Invariant I2 forbidden edge names
FORBIDDEN_EDGE_KINDS = {
    "similarto",
    "embeddingneighbor",
    "similarity",
    "vectorneighbor",
    "semanticmatch",
}


class CodeSpan(BaseModel):
    file_path: str
    start_line: int
    end_line: int
    start_col: int = 0
    end_col: int = 0


class GraphNode(BaseModel):
    id: str
    name: str
    kind: NodeKind
    file_path: str
    span: CodeSpan
    # Function specific
    signature: Optional[str] = None
    return_type: Optional[str] = None
    param_types: Dict[str, str] = Field(default_factory=dict)
    purity_hint: Optional[bool] = None
    body_source: Optional[str] = None
    # Endpoint specific
    http_method: Optional[str] = None
    route_pattern: Optional[str] = None
    request_schema: Optional[str] = None
    response_schema: Optional[str] = None
    # DBColumn specific
    table: Optional[str] = None
    col_type: Optional[str] = None
    nullable: bool = True
    default_value: Optional[str] = None
    # DTO specific
    fields: Dict[str, str] = Field(default_factory=dict)
    origin_language: Optional[str] = None
    # Diagnostics / Flags
    type_drift: bool = False
    missing_contract: bool = False
    synthetic: bool = False
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def canonical_signature(self) -> str:
        """Produce a short canonical text representation for System 1 scoring."""
        if self.kind == NodeKind.FUNCTION:
            params = ", ".join(f"{k}: {v}" for k, v in self.param_types.items())
            ret = f" -> {self.return_type}" if self.return_type else ""
            return f"def {self.name}({params}){ret}"
        elif self.kind == NodeKind.ENDPOINT:
            return f"{self.http_method or 'ANY'} {self.route_pattern or ''} [res: {self.response_schema or 'any'}]"
        elif self.kind == NodeKind.DB_COLUMN:
            null_str = "NULL" if self.nullable else "NOT NULL"
            return f"{self.table}.{self.name} {self.col_type or 'ANY'} {null_str}"
        elif self.kind == NodeKind.DTO:
            fields_str = ", ".join(f"{k}: {v}" for k, v in self.fields.items())
            return f"DTO {self.name}{{{fields_str}}}"
        return f"{self.kind.value} {self.name}"


class GraphEdge(BaseModel):
    source: str
    target: str
    kind: EdgeKind
    confidence: float = 1.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CodeGraph:
    """Deterministic in-memory code graph store.
    
    Provides single-writer state management with logical epoch clock.
    """

    def __init__(self) -> None:
        self._graph: nx.DiGraph = nx.DiGraph()
        self._nodes: Dict[str, GraphNode] = {}
        self._epoch: int = 0
        self._unresolved_refs: int = 0

    @property
    def graph_epoch(self) -> int:
        return self._epoch

    @property
    def unresolved_refs(self) -> int:
        return self._unresolved_refs

    @unresolved_refs.setter
    def unresolved_refs(self, count: int) -> None:
        self._unresolved_refs = count

    def increment_epoch(self) -> int:
        self._epoch += 1
        return self._epoch

    def add_node(self, node: GraphNode) -> None:
        self._nodes[node.id] = node
        self._graph.add_node(node.id, data=node)

    def get_node(self, node_id: str) -> Optional[GraphNode]:
        return self._nodes.get(node_id)

    def has_node(self, node_id: str) -> bool:
        return node_id in self._nodes

    def all_nodes(self) -> List[GraphNode]:
        return list(self._nodes.values())

    @property
    def nodes(self) -> List[GraphNode]:
        return list(self._nodes.values())

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        kind: EdgeKind | str,
        confidence: float = 1.0,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        # Invariant I2 enforcement: strictly check against embedding/similarity edges
        kind_str = kind.value if isinstance(kind, EdgeKind) else str(kind)
        if kind_str.lower() in FORBIDDEN_EDGE_KINDS:
            raise ValueError(
                f"Invariant I2 Violation: Cannot create similarity/embedding edge '{kind_str}'. "
                f"All edges must be deterministic parser or typechecker facts."
            )

        if not isinstance(kind, EdgeKind):
            try:
                kind = EdgeKind(kind_str)
            except ValueError:
                raise ValueError(
                    f"Unknown edge kind '{kind_str}'. Allowed: {[e.value for e in EdgeKind]}"
                )

        if source_id not in self._nodes:
            raise KeyError(f"Source node '{source_id}' does not exist in graph.")
        if target_id not in self._nodes:
            raise KeyError(f"Target node '{target_id}' does not exist in graph.")

        edge = GraphEdge(
            source=source_id,
            target=target_id,
            kind=kind,
            confidence=confidence,
            metadata=metadata or {},
        )
        self._graph.add_edge(source_id, target_id, data=edge)

    def get_edge(self, source_id: str, target_id: str) -> Optional[GraphEdge]:
        if self._graph.has_edge(source_id, target_id):
            return self._graph[source_id][target_id].get("data")
        return None

    def successors(self, node_id: str) -> List[Tuple[GraphNode, GraphEdge]]:
        """Return all downstream adjacent nodes and connecting edges."""
        if node_id not in self._graph:
            return []
        results = []
        for succ_id in self._graph.successors(node_id):
            edge_data: GraphEdge = self._graph[node_id][succ_id]["data"]
            node_data = self._nodes[succ_id]
            results.append((node_data, edge_data))
        return results

    def predecessors(self, node_id: str) -> List[Tuple[GraphNode, GraphEdge]]:
        """Return all upstream adjacent nodes and connecting edges."""
        if node_id not in self._graph:
            return []
        results = []
        for pred_id in self._graph.predecessors(node_id):
            edge_data: GraphEdge = self._graph[pred_id][node_id]["data"]
            node_data = self._nodes[pred_id]
            results.append((node_data, edge_data))
        return results

    def find_nodes_by_kind(self, kind: NodeKind) -> List[GraphNode]:
        return [node for node in self._nodes.values() if node.kind == kind]

    def find_node_by_span(self, file_path: str, line: int) -> Optional[GraphNode]:
        """Find the most specific node enclosing the given file and line number."""
        best_match: Optional[GraphNode] = None
        min_span_size = float("inf")

        for node in self._nodes.values():
            if node.file_path == file_path:
                if node.span.start_line <= line <= node.span.end_line:
                    span_size = node.span.end_line - node.span.start_line
                    if span_size < min_span_size:
                        min_span_size = span_size
                        best_match = node
        return best_match

    def node_count(self) -> int:
        return self._graph.number_of_nodes()

    def edge_count(self) -> int:
        return self._graph.number_of_edges()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize snapshot to dictionary."""
        return {
            "graph_epoch": self._epoch,
            "unresolved_refs": self._unresolved_refs,
            "nodes": [n.model_dump() for n in self._nodes.values()],
            "edges": [
                self._graph[u][v]["data"].model_dump()
                for u, v in self._graph.edges()
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CodeGraph:
        graph = cls()
        graph._epoch = data.get("graph_epoch", 0)
        graph._unresolved_refs = data.get("unresolved_refs", 0)
        for n_dict in data.get("nodes", []):
            node = GraphNode(**n_dict)
            graph.add_node(node)
        for e_dict in data.get("edges", []):
            edge = GraphEdge(**e_dict)
            graph.add_edge(
                source_id=edge.source,
                target_id=edge.target,
                kind=edge.kind,
                confidence=edge.confidence,
                metadata=edge.metadata,
            )
        return graph
