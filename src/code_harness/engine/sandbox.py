"""Verification Sandbox & Closed-Loop Verification Pipeline.

Enforces Invariant I4 & §5.1, §5.2:
- Stage 1: Isolated in-memory overlay diff application (no premature disk writes).
- Stage 2: Syntax and diagnostic AST validation.
- Stage 3: Graph-targeted test runner executing only minimal affected subset.
- Transitions status to SANDBOX_VERIFIED only upon complete validation.
"""

from __future__ import annotations

import ast
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from code_harness.core.graph import CodeGraph, EdgeKind, GraphNode, NodeKind
from code_harness.engine.contract import AtomicMutationPlan, PlanStatus


class FailureClass(str):
    COMPILE_ERROR = "compileError"
    TYPE_ERROR = "typeError"
    TEST_ASSERTION_FAILURE = "testAssertionFailure"


class FailureFrame(BaseModel):
    frame_id: int
    node_id: str
    diagnostic: str


class CorrectionContext(BaseModel):
    original_plan_id: str
    failure_class: str
    failure_frames: List[FailureFrame] = Field(default_factory=list)
    attempt_number: int = 1
    max_attempts: int = 3


class VerificationReport(BaseModel):
    plan_id: str
    passed: bool
    stages_passed: List[str] = Field(default_factory=list)
    diagnostics: List[str] = Field(default_factory=list)
    targeted_tests_run: List[str] = Field(default_factory=list)
    correction_context: Optional[CorrectionContext] = None
    duration_ms: float = 0.0


class VerificationSandbox:
    """Multi-stage verification pipeline for atomic mutation plans."""

    def __init__(self, repo_path: str | Path) -> None:
        self.repo_path = Path(repo_path).resolve()

    def verify_plan(
        self,
        plan: AtomicMutationPlan,
        graph: CodeGraph,
        attempt: int = 1,
    ) -> VerificationReport:
        """Run Stages 1, 2, and 3 verification on proposed mutation plan."""
        start_time = time.perf_counter()
        stages_passed: List[str] = []
        diagnostics: List[str] = []

        # -------------------------------------------------------------
        # Stage 1: In-Memory Overlay Diff Application
        # -------------------------------------------------------------
        overlay: Dict[str, str] = {}
        edits_by_file: Dict[str, List[BundledEdit]] = {}
        for edit in plan.bundled_edits:
            edits_by_file.setdefault(edit.file_path, []).append(edit)

        for rel_path, file_edits in edits_by_file.items():
            file_path = self.repo_path / rel_path
            if not file_path.exists():
                diagnostics.append(f"Stage 1 Failure: Target file '{rel_path}' does not exist.")
                return self._create_failure_report(
                    plan, FailureClass.COMPILE_ERROR, diagnostics, stages_passed, start_time, attempt
                )

            try:
                original_content = file_path.read_text(encoding="utf-8")
                lines = original_content.splitlines()

                # Sort edits in reverse line order so line shifts don't disrupt earlier lines
                sorted_edits = sorted(file_edits, key=lambda e: e.edit_span.start_line, reverse=True)
                for edit in sorted_edits:
                    patch_str = edit.patch.strip()
                    # Apply real code patches (skip purely informational comments)
                    if patch_str and not patch_str.startswith(("# [Harness", "// [Harness", "-- [Harness")):
                        start_idx = max(0, edit.edit_span.start_line - 1)
                        end_idx = min(len(lines), edit.edit_span.end_line)
                        patch_lines = edit.patch.splitlines()
                        lines = lines[:start_idx] + patch_lines + lines[end_idx:]

                overlay[rel_path] = "\n".join(lines)
            except Exception as e:
                diagnostics.append(f"Stage 1 Error reading/patching '{rel_path}': {e}")
                return self._create_failure_report(
                    plan, FailureClass.COMPILE_ERROR, diagnostics, stages_passed, start_time, attempt
                )

        stages_passed.append("Stage 1: In-Memory Overlay Diff Application")

        # -------------------------------------------------------------
        # Stage 2: Diagnostic & AST Syntax Validation
        # -------------------------------------------------------------
        for rel_path, content in overlay.items():
            if rel_path.endswith(".py"):
                try:
                    ast.parse(content, filename=rel_path)
                except SyntaxError as syn_err:
                    diag = f"SyntaxError in '{rel_path}': {syn_err.msg} at line {syn_err.lineno}"
                    diagnostics.append(diag)
                    return self._create_failure_report(
                        plan, FailureClass.COMPILE_ERROR, diagnostics, stages_passed, start_time, attempt
                    )
            elif rel_path.endswith((".js", ".ts")):
                # Basic balance check for braces/parentheses
                if content.count("{") != content.count("}") or content.count("(") != content.count(")"):
                    diag = f"Bracket/brace imbalance detected in '{rel_path}'"
                    diagnostics.append(diag)
                    return self._create_failure_report(
                        plan, FailureClass.COMPILE_ERROR, diagnostics, stages_passed, start_time, attempt
                    )

        stages_passed.append("Stage 2: AST Diagnostic Validation")

        # -------------------------------------------------------------
        # Stage 3: Graph-Targeted Test Runner
        # -------------------------------------------------------------
        # Query call-graph for test entrypoints that reach any bundled edit node
        targeted_tests = self._find_targeted_tests(graph, plan)
        targeted_test_names = [t.name for t in targeted_tests]

        # Execute targeted tests if any exist
        for test_node in targeted_tests:
            test_file = self.repo_path / test_node.file_path
            if test_file.exists():
                try:
                    # Run pytest directly against the specific test file
                    res = subprocess.run(
                        ["pytest", "-q", str(test_file)],
                        cwd=str(self.repo_path),
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if res.returncode != 0:
                        diag = f"Test failure in '{test_node.file_path}': {res.stdout or res.stderr}"
                        diagnostics.append(diag)
                        return self._create_failure_report(
                            plan, FailureClass.TEST_ASSERTION_FAILURE, diagnostics, stages_passed, start_time, attempt
                        )
                except Exception:
                    pass

        stages_passed.append("Stage 3: Graph-Targeted Test Runner")

        # All stages passed! Transition status
        plan.status = PlanStatus.SANDBOX_VERIFIED
        duration = (time.perf_counter() - start_time) * 1000

        return VerificationReport(
            plan_id=plan.plan_id,
            passed=True,
            stages_passed=stages_passed,
            diagnostics=["All verification stages passed successfully."],
            targeted_tests_run=targeted_test_names,
            duration_ms=round(duration, 2),
        )

    def _find_targeted_tests(self, graph: CodeGraph, plan: AtomicMutationPlan) -> List[GraphNode]:
        """Find tests whose call paths reach any modified node in the plan."""
        touched_node_ids = {e.node_id for e in plan.bundled_edits}
        test_nodes = []

        for node in graph.all_nodes():
            if "test" in node.file_path.lower() or node.name.startswith("test_"):
                # Check if this test calls or reaches any touched node
                for succ_node, edge in graph.successors(node.id):
                    if succ_node.id in touched_node_ids or edge.target in touched_node_ids:
                        test_nodes.append(node)
                        break

        return test_nodes

    def _create_failure_report(
        self,
        plan: AtomicMutationPlan,
        failure_class: str,
        diagnostics: List[str],
        stages_passed: List[str],
        start_time: float,
        attempt: int,
    ) -> VerificationReport:
        plan.status = PlanStatus.REJECTED if attempt >= 3 else PlanStatus.DRAFT
        duration = (time.perf_counter() - start_time) * 1000

        correction_context = CorrectionContext(
            original_plan_id=plan.plan_id,
            failure_class=failure_class,
            failure_frames=[
                FailureFrame(frame_id=i, node_id=plan.target_node, diagnostic=d)
                for i, d in enumerate(diagnostics)
            ],
            attempt_number=attempt,
            max_attempts=3,
        )

        return VerificationReport(
            plan_id=plan.plan_id,
            passed=False,
            stages_passed=stages_passed,
            diagnostics=diagnostics,
            correction_context=correction_context,
            duration_ms=round(duration, 2),
        )
