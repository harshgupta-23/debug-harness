import pytest
from pathlib import Path

from code_harness.harness import Harness


@pytest.fixture
def workspace_harness():
    ws = Path(__file__).parent.parent / "mock_workspace"
    return Harness(repo_path=ws)


def test_get_outline(workspace_harness):
    outline = workspace_harness.get_outline()
    assert "routes.py" in outline
    symbols = [s["name"] for s in outline["routes.py"]]
    assert "compute_total" in symbols
    assert "get_order_details" in symbols


def test_multi_symptom_shared_root(workspace_harness):
    # Both test_compute_total_standard and get_order_details call compute_total (shared dependency/callee)
    state = workspace_harness.step(
        issue="Calculation and checkout errors",
        symptoms=["test_compute_total_standard", "get_order_details"],
        apply=False,
    )
    assert not state.done
    assert state.curr is not None
    # Shared root cause should be compute_total
    assert state.curr.name == "compute_total"
    assert state.session_id is not None

    # Check session log metadata
    logs = workspace_harness.format_logs(state.session_id)
    assert "Multi-Symptom Bug Cluster" in logs
    assert "compute_total" in logs
    assert "TRAVERSAL HISTORY" in logs


def test_multi_symptom_disjoint_queuing(workspace_harness):
    # Two nodes with no shared call paths: compute_total and String
    state = workspace_harness.step(
        issue="Multiple issues",
        symptoms=["compute_total", "String"],
        apply=False,
    )
    assert not state.done
    assert state.curr is not None
    # First symptom active
    assert state.curr.name == "compute_total"
    # Second symptom queued
    assert any("String" in q for q in state.pending_queue)

    logs = workspace_harness.format_logs(state.session_id)
    assert "Independent Bug Queries" in logs


def test_traversal_history_formatting(workspace_harness):
    # Step 1: Start
    s1 = workspace_harness.step(
        issue="Discount calculation bug",
        symptom="compute_total",
        apply=False,
    )
    sess_id = s1.session_id

    # Step 2: Patch curr and queue a neighbor
    upstreams = [d.node_id for d in s1.dependents_depth_1 if d.direction == "upstream"]
    s2 = workspace_harness.step(
        session_id=sess_id,
        curr_patch="def compute_total(price, qty, discount=0.0):\n    return price * qty - discount\n",
        modify_next_nodes=upstreams[:1],
        apply=False,
    )
    logs = workspace_harness.format_logs(sess_id)
    assert f"DEBUG HARNESS TRAVERSAL LOG | Session: {sess_id}" in logs
    assert "Step 1" in logs
    assert "Patched" in logs
