"""Tests for System 1 Scorer and Softmax temperature calibration."""

from code_harness.core.graph import CodeSpan, EdgeKind, GraphEdge, GraphNode, NodeKind
from code_harness.engine.system1 import System1Scorer


def test_system1_softmax_temperature_calibration():
    scorer = System1Scorer(temperature=0.5)

    span = CodeSpan(file_path="routes.py", start_line=1, end_line=5)
    node1 = GraphNode(id="fn:calc_total", name="calc_total", kind=NodeKind.FUNCTION, file_path="routes.py", span=span)
    node2 = GraphNode(id="fn:send_email", name="send_email", kind=NodeKind.FUNCTION, file_path="routes.py", span=span)

    edge1 = GraphEdge(source="fn:caller", target="fn:calc_total", kind=EdgeKind.CALLS, confidence=1.0)
    edge2 = GraphEdge(source="fn:caller", target="fn:send_email", kind=EdgeKind.CALLS, confidence=1.0)

    candidates = [
        (node1, edge1, ["fn:caller"]),
        (node2, edge2, ["fn:caller"]),
    ]

    ranked = scorer.score_candidates("total discount calculation", candidates)
    assert len(ranked) == 2
    # Probability distribution sums to ~1.0
    total_prob = sum(c.calibrated_score for c in ranked)
    assert abs(total_prob - 1.0) < 0.05
    # calc_total should outrank send_email for total calculation
    assert ranked[0].node.id == "fn:calc_total"
