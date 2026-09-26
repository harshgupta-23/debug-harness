"""Tests for Blast Radius reachability and fan-out policy."""

from code_harness.core.graph import CodeGraph, CodeSpan, EdgeKind, GraphNode, NodeKind
from code_harness.engine.blast_radius import BlastRadiusEngine, SafetyPolicy


def test_blast_radius_fanout_policy():
    graph = CodeGraph()
    span = CodeSpan(file_path="app.py", start_line=1, end_line=5)

    target = GraphNode(id="fn:target", name="target", kind=NodeKind.FUNCTION, file_path="app.py", span=span)
    graph.add_node(target)

    # Add 5 direct callers (below threshold of 20)
    for i in range(5):
        caller = GraphNode(id=f"fn:caller_{i}", name=f"caller_{i}", kind=NodeKind.FUNCTION, file_path="app.py", span=span)
        graph.add_node(caller)
        graph.add_edge(f"fn:caller_{i}", "fn:target", EdgeKind.CALLS)

    engine = BlastRadiusEngine(max_fanout_threshold=20)
    report = engine.compute_blast_radius(graph, "fn:target")

    assert report.direct_dependents == 5
    assert report.policy == SafetyPolicy.MANDATORY_BUNDLE

    # Add 20 more callers (total 25 > 20)
    for i in range(5, 25):
        caller = GraphNode(id=f"fn:caller_{i}", name=f"caller_{i}", kind=NodeKind.FUNCTION, file_path="app.py", span=span)
        graph.add_node(caller)
        graph.add_edge(f"fn:caller_{i}", "fn:target", EdgeKind.CALLS)

    report_high = engine.compute_blast_radius(graph, "fn:target")
    assert report_high.policy == SafetyPolicy.BACKWARD_COMPAT_SHIM_REQUIRED
