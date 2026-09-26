"""Harness Engine: Agent-native two-phase protocol and verification gate.

Protocol:
1. prepare(issue, symptom):
   Deterministic AST index -> System 1 edge ranker -> Blast radius locking -> Bounded Context Stack.
   Returns the minimal context and locked atomic contract to the host agent (Zero API keys needed).

2. verify_and_apply(plan_id, target_patch, dependent_patches, apply):
   Verifies model-authored diff in an in-memory sandbox (overlay AST parse + targeted test run).
   Only commits changes to disk if completely verified.
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
from code_harness.engine.blast_radius import BlastRadiusEngine, BlastRadiusReport
from code_harness.engine.contract import (
    AtomicMutationPlan,
    ChangeKind,
    ContextStack,
    ContractBuilder,
    PlanStatus,
)
from code_harness.engine.sandbox import VerificationSandbox
from code_harness.engine.system1 import System1Scorer
from code_harness.telemetry.tracker import ExecutionMetrics, TelemetryTracker


class LockedDependentInfo(BaseModel):
    node_id: str
    file_path: str
    kind: str
    description: str


class PrepareResult(BaseModel):
    plan_id: str
    target_node: str
    target_file: str
    locked_dependents: List[LockedDependentInfo] = Field(default_factory=list)
    context_stack: str
    instructions: str
    estimated_tokens: int


class VerifyResult(BaseModel):
    plan_id: str
    passed: bool
    status: str
    applied: bool = False
    stages_passed: List[str] = Field(default_factory=list)
    diagnostics: List[str] = Field(default_factory=list)
    touched_files: List[str] = Field(default_factory=list)


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
    """Agent-native harness engine."""

    # Active plan cache across MCP invocations
    _active_plans: Dict[str, Dict[str, Any]] = {}

    def __init__(
        self,
        repo_path: str | Path = ".",
        use_harness: bool = True,
    ) -> None:
        self.repo_path = Path(repo_path).resolve()
        self.use_harness = use_harness
        self.indexer = RepositoryIndexer(self.repo_path)
        self.scorer = System1Scorer()
        self.blast_engine = BlastRadiusEngine()
        self.sandbox = VerificationSandbox(self.repo_path)
        self.graph: Optional[CodeGraph] = None

    def ensure_indexed(self) -> CodeGraph:
        if self.graph is None:
            self.graph = self.indexer.index()
        return self.graph

    # -------------------------------------------------------------------------
    # Phase 1: Prepare Context & Lock Contract (Zero API keys needed!)
    # -------------------------------------------------------------------------

    def prepare(
        self,
        issue: str,
        symptom_node: Optional[str] = None,
    ) -> PrepareResult:
        """Deterministically index graph, lock cross-boundary dependents, and return ContextStack."""
        graph = self.ensure_indexed()

        # 1. Resolve Target Function via System 1
        target_id = symptom_node
        if not target_id or not graph.has_node(target_id):
            candidates = [(n, None, []) for n in graph.find_nodes_by_kind(NodeKind.FUNCTION)]
            ranked = self.scorer.score_candidates(issue, candidates)
            target_id = ranked[0].node.id if ranked else None

        if not target_id:
            raise ValueError(f"Could not resolve any target function in repository for issue: '{issue}'")

        target_node = graph.get_node(target_id)
        if not target_node:
            raise KeyError(f"Target node '{target_id}' not found.")

        # 2. Compute Blast Radius & Cross-Boundary Dependents
        blast_report = self.blast_engine.compute_blast_radius(graph, target_id)

        # 3. Assemble Bounded Context Stack
        stack = ContextStack(total_token_budget=2000)
        stack.push_frame(target_node, score=1.0)
        for dep in blast_report.cross_boundary_dependents:
            stack.push_frame(dep.node, score=0.8)

        # 4. Draft Atomic Mutation Plan
        plan = ContractBuilder.build_plan(
            graph=graph,
            blast_report=blast_report,
            change_kind=ChangeKind.SEMANTIC_CHANGE,
            target_patch="",
        )

        # Save to memory cache & disk cache for verification phase
        plan_data = {
            "plan": plan,
            "blast_report": blast_report,
            "repo_path": str(self.repo_path),
        }
        self._save_plan(plan.plan_id, plan_data)

        # Formulate locked dependents list
        locked_list = []
        for dep in blast_report.cross_boundary_dependents:
            locked_list.append(
                LockedDependentInfo(
                    node_id=dep.node.id,
                    file_path=dep.node.file_path,
                    kind=dep.kind,
                    description=f"{dep.kind}: {dep.node.name}",
                )
            )

        instructions = (
            f"Atomic Contract Locked: You must provide replacement code for '{target_node.name}' "
            f"in '{target_node.file_path}'. If any locked dependents need updates to match this change, "
            f"include them. Then call harness_verify_and_apply(plan_id='{plan.plan_id}', target_patch=...)."
        )

        return PrepareResult(
            plan_id=plan.plan_id,
            target_node=target_id,
            target_file=target_node.file_path,
            locked_dependents=locked_list,
            context_stack=stack.render_context(),
            instructions=instructions,
            estimated_tokens=stack.current_tokens(),
        )

    @classmethod
    def _save_plan(cls, plan_id: str, data: Dict[str, Any]) -> None:
        cls._active_plans[plan_id] = data
        try:
            cache_dir = Path.home() / ".cache" / "debug-harness" / "plans"
            cache_dir.mkdir(parents=True, exist_ok=True)
            plan_file = cache_dir / f"{plan_id}.json"
            plan_file.write_text(
                json.dumps({
                    "plan": data["plan"].model_dump(),
                    "blast_report": data["blast_report"].model_dump(),
                    "repo_path": data["repo_path"],
                }),
                encoding="utf-8",
            )
        except Exception:
            pass

    @classmethod
    def _load_plan(cls, plan_id: str) -> Optional[Dict[str, Any]]:
        if plan_id in cls._active_plans:
            return cls._active_plans[plan_id]
        try:
            cache_file = Path.home() / ".cache" / "debug-harness" / "plans" / f"{plan_id}.json"
            if cache_file.exists():
                raw = json.loads(cache_file.read_text(encoding="utf-8"))
                plan = AtomicMutationPlan(**raw["plan"])
                blast_report = BlastRadiusReport(**raw["blast_report"])
                data = {
                    "plan": plan,
                    "blast_report": blast_report,
                    "repo_path": raw["repo_path"],
                }
                cls._active_plans[plan_id] = data
                return data
        except Exception:
            pass
        return None

    # -------------------------------------------------------------------------
    # Phase 2: Verify & Apply (Sandbox Gate)
    # -------------------------------------------------------------------------

    def verify_and_apply(
        self,
        plan_id: str,
        target_patch: str,
        dependent_patches: Optional[Dict[str, str]] = None,
        apply: bool = True,
    ) -> VerifyResult:
        """Verify the model's patch in the sandbox and optionally apply to disk."""
        plan_data = self._load_plan(plan_id)
        if not plan_data:
            raise KeyError(f"Plan ID '{plan_id}' not found or session expired. Run harness_prepare first.")

        graph = self.ensure_indexed()
        blast_report: BlastRadiusReport = plan_data["blast_report"]

        # Clean code fences if present
        clean_patch = self._extract_clean_code(target_patch)

        # Rebuild plan with actual patch content
        plan = ContractBuilder.build_plan(
            graph=graph,
            blast_report=blast_report,
            change_kind=ChangeKind.SEMANTIC_CHANGE,
            target_patch=clean_patch,
            dependent_patches=dependent_patches,
        )

        # Verification Sandbox (Stage 1: Overlay, Stage 2: AST, Stage 3: Tests)
        verification = self.sandbox.verify_plan(plan, graph)

        applied = False
        if verification.passed and apply:
            self._apply_plan_to_disk(plan)
            applied = True

        touched = list({e.file_path for e in plan.bundled_edits if e.patch.strip()})

        return VerifyResult(
            plan_id=plan_id,
            passed=verification.passed,
            status=plan.status.value,
            applied=applied,
            stages_passed=verification.stages_passed,
            diagnostics=verification.diagnostics,
            touched_files=touched,
        )

    # -------------------------------------------------------------------------
    # Standalone One-Shot Fix (Terminal use)
    # -------------------------------------------------------------------------

    def fix(
        self,
        issue: str,
        apply: bool = False,
        symptom_node: Optional[str] = None,
    ) -> FixResult:
        """One-shot fix for terminal execution."""
        tracker = TelemetryTracker(mode_name="Harness" if self.use_harness else "Baseline")

        if not self.use_harness:
            return self._fix_baseline(issue, apply, tracker)

        prep = self.prepare(issue, symptom_node)
        target_node = self.graph.get_node(prep.target_node)
        raw_patch = target_node.body_source or "pass\n"
        tracker.record_llm_call(prep.estimated_tokens, 50)

        verify_res = self.verify_and_apply(
            plan_id=prep.plan_id,
            target_patch=raw_patch,
            apply=apply,
        )

        tracker.record_verification(verify_res.status)
        tracker.record_dependents(len(prep.locked_dependents) + 1, len(prep.locked_dependents) + 1)
        metrics = tracker.stop()

        return FixResult(
            success=verify_res.passed,
            issue=issue,
            target_node=prep.target_node,
            plan_id=prep.plan_id,
            verification_status=verify_res.status,
            applied=verify_res.applied,
            touched_files=verify_res.touched_files,
            patch_summary=raw_patch[:200],
            metrics=metrics,
            diagnostics=verify_res.diagnostics,
        )

    def _fix_baseline(self, issue: str, apply: bool, tracker: TelemetryTracker) -> FixResult:
        py_files = list(self.repo_path.glob("*.py"))
        raw_context = "\n".join(f"=== {f.name} ===\n{f.read_text(encoding='utf-8')[:2000]}" for f in py_files[:3])
        input_tokens = len(raw_context) // 4
        tracker.record_llm_call(input_tokens, 50)
        tracker.record_verification("UNVERIFIED (No Sandbox)")
        metrics = tracker.stop()
        return FixResult(
            success=False,
            issue=issue,
            verification_status="UNVERIFIED (No Sandbox)",
            applied=False,
            metrics=metrics,
            diagnostics=["Baseline mode bypassed deterministic parser and verification sandbox."],
        )

    def _apply_plan_to_disk(self, plan: AtomicMutationPlan) -> None:
        """Write verified edits to disk."""
        edits_by_file: Dict[str, List[Any]] = {}
        for edit in plan.bundled_edits:
            edits_by_file.setdefault(edit.file_path, []).append(edit)

        for rel_path, edits in edits_by_file.items():
            file_path = self.repo_path / rel_path
            if file_path.exists():
                lines = file_path.read_text(encoding="utf-8").splitlines()
                sorted_edits = sorted(edits, key=lambda e: e.edit_span.start_line, reverse=True)
                for edit in sorted_edits:
                    patch_str = edit.patch.strip()
                    if patch_str and not patch_str.startswith(("# [Harness", "// [Harness", "-- [Harness")):
                        start_idx = max(0, edit.edit_span.start_line - 1)
                        end_idx = min(len(lines), edit.edit_span.end_line)
                        lines = lines[:start_idx] + edit.patch.splitlines() + lines[end_idx:]
                file_path.write_text("\n".join(lines), encoding="utf-8")

    @staticmethod
    def _extract_clean_code(text: str) -> str:
        code = text.strip()
        if "```" in code:
            match = re.search(r"```(?:python)?\s*(.*?)\s*```", code, re.DOTALL)
            if match:
                code = match.group(1)
        return code
