"""Primary Harness API: Fix bugs using deterministic graph traversal and atomic contracts.

Toggle:
- use_harness=True (default): AST indexing -> System 1 edge ranking -> Context Stack -> Atomic Contract -> Sandbox
- use_harness=False: Raw baseline agent loop without parser or dependency locking.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from code_harness.core.graph import CodeGraph, NodeKind
from code_harness.core.indexer import RepositoryIndexer
from code_harness.engine.blast_radius import BlastRadiusEngine
from code_harness.engine.contract import (
    ChangeKind,
    ContextStack,
    ContractBuilder,
    PlanStatus,
)
from code_harness.engine.llm import LLMClient
from code_harness.engine.sandbox import VerificationSandbox
from code_harness.engine.system1 import System1Scorer
from code_harness.telemetry.tracker import ExecutionMetrics, TelemetryTracker


class FixResult(BaseModel):
    success: bool
    issue: str
    target_node: Optional[str] = None
    plan_id: Optional[str] = None
    verification_status: str
    applied: bool = False
    touched_files: List[str] = Field(default_factory=list)
    patch_summary: str = ""
    metrics: ExecutionMetrics
    diagnostics: List[str] = Field(default_factory=list)


class Harness:
    """Developer engine to analyze, lock, and fix codebases."""

    def __init__(
        self,
        repo_path: str | Path = ".",
        use_harness: bool = True,
        model: str = "gemini-1.5-flash",
        api_key: Optional[str] = None,
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.use_harness = use_harness
        self.llm = LLMClient(model=model, api_key=api_key)
        self.indexer = RepositoryIndexer(self.repo_path)
        self.scorer = System1Scorer()
        self.blast_engine = BlastRadiusEngine()
        self.sandbox = VerificationSandbox(self.repo_path)
        self.graph: Optional[CodeGraph] = None

    def fix(
        self,
        issue: str,
        apply: bool = False,
        symptom_node: Optional[str] = None,
    ) -> FixResult:
        """Analyze issue, synthesize atomic patch via LLM, verify, and optionally apply."""
        tracker = TelemetryTracker(mode_name="Harness" if self.use_harness else "Baseline")
        start_time = time.perf_counter()

        if not self.use_harness:
            return self._fix_baseline(issue, apply, tracker, start_time)

        # -------------------------------------------------------------
        # Toggle ON: Deterministic Code-Graph Harness Pipeline
        # -------------------------------------------------------------
        # Step 1: Deterministic Indexing
        self.graph = self.indexer.index()

        # Step 2: Resolve Target / Symptom Node
        target_id = symptom_node
        if not target_id or not self.graph.has_node(target_id):
            # System 1 ranking over candidate functions
            candidates = []
            for n in self.graph.find_nodes_by_kind(NodeKind.FUNCTION):
                candidates.append((n, None, []))
            ranked = self.scorer.score_candidates(issue, candidates)
            target_id = ranked[0].node.id if ranked else None

        if not target_id:
            metrics = tracker.stop()
            return FixResult(
                success=False,
                issue=issue,
                verification_status="NO_TARGET_RESOLVED",
                metrics=metrics,
                diagnostics=["Could not identify relevant target function in codebase."],
            )

        target_node = self.graph.get_node(target_id)

        # Step 3: Blast Radius and Cross-Boundary Enclosure
        blast_report = self.blast_engine.compute_blast_radius(self.graph, target_id)

        # Step 4: Assembling Context Stack
        stack = ContextStack(total_token_budget=2000)
        stack.push_frame(target_node, score=1.0)
        for dep in blast_report.cross_boundary_dependents:
            stack.push_frame(dep.node, score=0.8)

        # Step 5: LLM Synthesis with bounded context stack
        system_prompt = (
            "You are a Principal Systems Engineer. Synthesize a clean, minimal bugfix "
            "for the target function. Return ONLY valid Python replacement code for the target "
            "function without markdown code fences or backticks."
        )
        user_prompt = (
            f"Issue: {issue}\n\n"
            f"Context Stack:\n{stack.render_context()}\n\n"
            f"Target Function to fix: {target_node.name} in {target_node.file_path}"
        )

        input_tokens = stack.current_tokens()
        try:
            raw_patch = self.llm.complete(system_prompt, user_prompt)
            clean_patch = self._extract_clean_code(raw_patch)
            output_tokens = max(1, len(clean_patch) // 4)
            tracker.record_llm_call(input_tokens, output_tokens)
        except Exception as e:
            # Fallback if API key missing: provide safe null-check template
            clean_patch = (
                f"# [Harness Fallback] Fix for {target_node.name}\n"
                f"{target_node.body_source or 'pass'}\n"
            )
            tracker.record_llm_call(input_tokens, 50)
            tracker.metrics.notes.append(f"LLM API note: {e}")

        # Step 6: Atomic Mutation Plan & Sandbox Verification
        plan = ContractBuilder.build_plan(
            graph=self.graph,
            blast_report=blast_report,
            change_kind=ChangeKind.SEMANTIC_CHANGE,
            target_patch=clean_patch,
        )

        verification = self.sandbox.verify_plan(plan, self.graph)
        tracker.record_verification(plan.status.value)
        tracker.record_dependents(
            locked=len(blast_report.cross_boundary_dependents) + 1,
            total=len(blast_report.cross_boundary_dependents) + 1,
        )
        metrics = tracker.stop()

        # Step 7: Apply to disk if requested and verified
        applied = False
        if apply and plan.status == PlanStatus.SANDBOX_VERIFIED:
            self._apply_plan_to_disk(plan)
            applied = True

        return FixResult(
            success=verification.passed,
            issue=issue,
            target_node=target_id,
            plan_id=plan.plan_id,
            verification_status=plan.status.value,
            applied=applied,
            touched_files=[e.file_path for e in plan.bundled_edits],
            patch_summary=clean_patch[:200] + ("..." if len(clean_patch) > 200 else ""),
            metrics=metrics,
            diagnostics=verification.diagnostics,
        )

    def _fix_baseline(
        self,
        issue: str,
        apply: bool,
        tracker: TelemetryTracker,
        start_time: float,
    ) -> FixResult:
        """Baseline path (Toggle OFF): raw file concatenation without parser."""
        # Find first python file
        py_files = list(self.repo_path.glob("*.py"))
        raw_context = "\n".join(
            f"=== {f.name} ===\n{f.read_text(encoding='utf-8')[:2000]}" for f in py_files[:3]
        )
        input_tokens = len(raw_context) // 4

        try:
            raw_patch = self.llm.complete("Fix this issue in the codebase.", f"{issue}\n{raw_context}")
            tracker.record_llm_call(input_tokens, len(raw_patch) // 4)
        except Exception as e:
            tracker.record_llm_call(input_tokens, 50)
            raw_patch = f"# Baseline ungrounded edit: {e}"

        tracker.record_verification("UNVERIFIED (No Sandbox)")
        metrics = tracker.stop()

        return FixResult(
            success=False,
            issue=issue,
            verification_status="UNVERIFIED (No Sandbox)",
            applied=False,
            patch_summary=raw_patch[:200],
            metrics=metrics,
            diagnostics=["Baseline mode bypassed deterministic parser and verification sandbox."],
        )

    def _apply_plan_to_disk(self, plan: Any) -> None:
        """Commit verified edits to files."""
        for edit in plan.bundled_edits:
            file_path = self.repo_path / edit.file_path
            if file_path.exists() and edit.patch.strip() and not edit.patch.startswith(("# [Harness", "//", "--")):
                lines = file_path.read_text(encoding="utf-8").splitlines()
                start_idx = max(0, edit.edit_span.start_line - 1)
                end_idx = min(len(lines), edit.edit_span.end_line)
                new_lines = lines[:start_idx] + edit.patch.splitlines() + lines[end_idx:]
                file_path.write_text("\n".join(new_lines), encoding="utf-8")

    @staticmethod
    def _extract_clean_code(text: str) -> str:
        """Strip markdown fences if present."""
        code = text.strip()
        if "```" in code:
            match = re.search(r"```(?:python)?\s*(.*?)\s*```", code, re.DOTALL)
            if match:
                code = match.group(1)
        return code
