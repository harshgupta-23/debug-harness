"""Tests for CodeGraph store and Invariants I1 & I2."""

import pytest
from code_harness.core.graph import (
    CodeGraph,
    CodeSpan,
    EdgeKind,
    GraphNode,
    NodeKind,
)


def test_graph_add_nodes_and_edges():
    graph = CodeGraph()
    span = CodeSpan(file_path="routes.py", start_line=1, end_line=10)

    node1 = GraphNode(id="fn:routes.py#foo", name="foo", kind=NodeKind.FUNCTION, file_path="routes.py", span=span)
    node2 = GraphNode(id="fn:routes.py#bar", name="bar", kind=NodeKind.FUNCTION, file_path="routes.py", span=span)

    graph.add_node(node1)
    graph.add_node(node2)

    assert graph.node_count() == 2
    assert graph.get_node("fn:routes.py#foo") == node1

    graph.add_edge("fn:routes.py#foo", "fn:routes.py#bar", EdgeKind.CALLS, confidence=1.0)
    assert graph.edge_count() == 1

    succs = graph.successors("fn:routes.py#foo")
    assert len(succs) == 1
    assert succs[0][0].id == "fn:routes.py#bar"


def test_invariant_i2_forbids_similarity_edges():
    graph = CodeGraph()
    span = CodeSpan(file_path="routes.py", start_line=1, end_line=10)
    node1 = GraphNode(id="n1", name="n1", kind=NodeKind.FUNCTION, file_path="a.py", span=span)
    node2 = GraphNode(id="n2", name="n2", kind=NodeKind.FUNCTION, file_path="b.py", span=span)
    graph.add_node(node1)
    graph.add_node(node2)

    # Invariant I2 forbids similarity or embedding edges
    with pytest.raises(ValueError, match="Invariant I2 Violation"):
        graph.add_edge("n1", "n2", "SimilarTo")

    with pytest.raises(ValueError, match="Invariant I2 Violation"):
        graph.add_edge("n1", "n2", "EmbeddingNeighbor")


def test_epoch_increment_and_serialization():
    graph = CodeGraph()
    assert graph.graph_epoch == 0
    graph.increment_epoch()
    assert graph.graph_epoch == 1

    span = CodeSpan(file_path="routes.py", start_line=1, end_line=10)
    node = GraphNode(id="fn:a", name="a", kind=NodeKind.FUNCTION, file_path="routes.py", span=span)
    graph.add_node(node)

    data = graph.to_dict()
    assert data["graph_epoch"] == 1
    assert len(data["nodes"]) == 1

    restored = CodeGraph.from_dict(data)
    assert restored.graph_epoch == 1
    assert restored.node_count() == 1
    assert restored.get_node("fn:a") is not None
