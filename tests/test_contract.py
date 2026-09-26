"""Tests for Atomic Mutation Plan and Context Stack Protocol."""

from code_harness.core.graph import CodeGraph, CodeSpan, EdgeKind, GraphNode, NodeKind
from code_harness.engine.blast_radius import BlastRadiusReport, SafetyPolicy
from code_harness.engine.contract import (
    ChangeKind,
    ContextStack,
    ContractBuilder,
    PlanStatus,
)


def test_context_stack_eviction_under_budget():
    stack = ContextStack(total_token_budget=50)  # very small budget

    span = CodeSpan(file_path="a.py", start_line=1, end_line=5)
    node1 = GraphNode(id="n1", name="n1", kind=NodeKind.FUNCTION, file_path="a.py", span=span, body_source="x = 1\n" * 20)
    node2 = GraphNode(id="n2", name="n2", kind=NodeKind.FUNCTION, file_path="a.py", span=span, body_source="y = 2\n" * 20)

    stack.push_frame(node1, score=0.9)
    stack.push_frame(node2, score=0.2)

    # Budget enforced: low score frame evicted
    assert len(stack.frames) <= 2
    assert stack.current_tokens() <= stack.total_token_budget or len(stack.frames) == 1


def test_contract_builder_locks_dependents():
    graph = CodeGraph()
    span = CodeSpan(file_path="routes.py", start_line=1, end_line=5)
    target = GraphNode(id="fn:target", name="target", kind=NodeKind.FUNCTION, file_path="routes.py", span=span)
    graph.add_node(target)

    blast_report = BlastRadiusReport(
        graph_epoch=1,
        target_node="fn:target",
        direct_dependents=1,
        transitive_dependents=0,
        cross_boundary_dependents=[],
        affected_nodes=[],
        policy=SafetyPolicy.MANDATORY_BUNDLE,
    )

    plan = ContractBuilder.build_plan(
        graph=graph,
        blast_report=blast_report,
        change_kind=ChangeKind.SIGNATURE_CHANGE,
        target_patch="def target(): pass\n",
    )

    assert plan.status == PlanStatus.DRAFT
    assert len(plan.bundled_edits) == 1
    assert "allDirectCallersUpdated" in plan.invariants_checked
