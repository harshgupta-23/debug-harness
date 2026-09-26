"""Deterministic Code-Graph Stepper Harness.

Provides a sequential 1-node-at-a-time graph traversal protocol:
- Focuses on 'curr' with exact AST code, file path, line range, and symbol name.
- Provides immediate depth-1 upstream and downstream neighbors with the same fields.
- Strictly restricts edits to ONLY 'curr'.
- Queues marked dependent links sequentially until all links return False/0.
- Verifies full atomic transaction in sandbox before applying to disk.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from code_harness.core.graph import CodeGraph, GraphNode, NodeKind
from code_harness.core.indexer import RepositoryIndexer
from code_harness.engine.blast_radius import BlastRadiusEngine
from code_harness.engine.contract import (
    AtomicMutationPlan,
    BundledEdit,
    ChangeKind,
    EditReason,
    PlanStatus,
)
from code_harness.engine.sandbox import VerificationSandbox
from code_harness.engine.system1 import System1Scorer


class NodeSlice(BaseModel):
    node_id: str
    file_path: str
    start_line: int
    end_line: int
    name: str
    kind: str
    code: str
    direction: Optional[str] = None      # "current", "upstream", "downstream"
    relationship: Optional[str] = None   # "Calls", "ReadsColumn", "ConsumesRoute", etc.


class StepState(BaseModel):
    session_id: str
    curr: Optional[NodeSlice] = None
    dependents_depth_1: List[NodeSlice] = Field(default_factory=list)
    pending_queue: List[str] = Field(default_factory=list)
    visited_nodes: List[str] = Field(default_factory=list)
    done: bool = False
    verification_status: str = "IN_PROGRESS"
    applied: bool = False
    touched_files: List[str] = Field(default_factory=list)
    diagnostics: List[str] = Field(default_factory=list)
    instructions: str = ""


class Harness:
    """Graph stepper engine driving 1-node-at-a-time traversal and sandbox gating."""

    # Active session state: session_id -> dict
    _sessions: Dict[str, Dict[str, Any]] = {}

    def __init__(self, repo_path: str | Path = ".") -> None:
        self.repo_path = Path(repo_path).resolve()
        self.indexer = RepositoryIndexer(self.repo_path)
        self.scorer = System1Scorer()
        self.blast_engine = BlastRadiusEngine()
        self.sandbox = VerificationSandbox(self.repo_path)
        self.graph: Optional[CodeGraph] = None

    def ensure_indexed(self) -> CodeGraph:
        if self.graph is None:
            self.graph = self.indexer.index()
        return self.graph

    def step(
        self,
        session_id: Optional[str] = None,
        issue: Optional[str] = None,
        symptom: Optional[str] = None,
        curr_patch: Optional[str] = None,
        modify_next_nodes: Optional[List[str]] = None,
        apply: bool = True,
    ) -> StepState:
        """Advance one node in the code graph or initialize a new session."""
        graph = self.ensure_indexed()

        # -------------------------------------------------------------
        # 1. Initialize New Session
        # -------------------------------------------------------------
        session_data = self._load_session(session_id) if session_id else None
        if not session_data:
            sess_id = session_id or f"step_{uuid.uuid4().hex[:8]}"

            # Resolve starting target node
            target_id = symptom
            if not target_id or not graph.has_node(target_id):
                candidates = [(n, None, []) for n in graph.find_nodes_by_kind(NodeKind.FUNCTION)]
                ranked = self.scorer.score_candidates(issue or "error", candidates)
                target_id = ranked[0].node.id if ranked else None

            if not target_id or not graph.has_node(target_id):
                return StepState(
                    session_id=sess_id,
                    done=True,
                    verification_status="FAILED",
                    diagnostics=[f"Could not resolve starting symbol for issue: '{issue}'"],
                )

            session_data = {
                "session_id": sess_id,
                "repo_path": str(self.repo_path),
                "curr_id": target_id,
                "pending_queue": [],
                "visited_nodes": [target_id],
                "patches": {},  # node_id -> patch_code
                "apply": apply,
            }
            self._save_session(sess_id, session_data)
            return self._build_step_state(sess_id, session_data, graph)

        # -------------------------------------------------------------
        # 2. Advance Existing Session
        # -------------------------------------------------------------
        session_data = self._load_session(session_id)
        curr_id = session_data["curr_id"]
        pending_queue: List[str] = session_data.get("pending_queue", [])
        visited: List[str] = session_data.get("visited_nodes", [])
        patches: Dict[str, str] = session_data.get("patches", {})

        # Record patch for curr (strict enforcement: only curr is recorded)
        if curr_patch and curr_patch.strip():
            patches[curr_id] = self._extract_clean_code(curr_patch)

        # Queue marked neighbors to modify next (if not already visited or queued)
        for next_id in (modify_next_nodes or []):
            if graph.has_node(next_id) and next_id not in visited and next_id not in pending_queue:
                pending_queue.append(next_id)

        # -------------------------------------------------------------
        # 3. Step to Next Node or Complete
        # -------------------------------------------------------------
        if pending_queue:
            # Advance to next link sequentially
            next_curr_id = pending_queue.pop(0)
            visited.append(next_curr_id)
            session_data["curr_id"] = next_curr_id
            session_data["pending_queue"] = pending_queue
            session_data["visited_nodes"] = visited
            session_data["patches"] = patches
            self._save_session(session_id, session_data)
            return self._build_step_state(session_id, session_data, graph)

        # All links processed (queue is empty) -> Verify and Apply
        session_data["pending_queue"] = []
        session_data["patches"] = patches
        return self._finish_session(session_id, session_data, graph, apply)

    # -----------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------

    def _build_step_state(
        self,
        session_id: str,
        session_data: Dict[str, Any],
        graph: CodeGraph,
    ) -> StepState:
        curr_id = session_data["curr_id"]
        curr_node = graph.get_node(curr_id)
        if not curr_node:
            raise KeyError(f"Node '{curr_id}' not found in graph.")

        curr_slice = self._slice_node(curr_node, direction="current")

        # Gather depth-1 upstream (callers, readers) and downstream (callees, endpoints)
        neighbors: List[NodeSlice] = []
        seen = {curr_id}

        # Upstream: predecessors in graph
        for pred, edge in graph.predecessors(curr_id):
            if pred.id not in seen:
                seen.add(pred.id)
                neighbors.append(self._slice_node(pred, direction="upstream", relationship=edge.kind.value))

        # Downstream: successors in graph
        for succ, edge in graph.successors(curr_id):
            if succ.id not in seen:
                seen.add(succ.id)
                neighbors.append(self._slice_node(succ, direction="downstream", relationship=edge.kind.value))

        # If endpoint, add consumers
        if curr_node.kind == NodeKind.ENDPOINT:
            for pred, edge in graph.predecessors(curr_id):
                if pred.id not in seen:
                    seen.add(pred.id)
                    neighbors.append(self._slice_node(pred, direction="upstream", relationship="ConsumesRoute"))

        instructions = (
            f"YOU ARE STRICTLY RESTRICTED TO MODIFY ONLY 'curr' ({curr_slice.name} in {curr_slice.file_path}, "
            f"lines {curr_slice.start_line}-{curr_slice.end_line}). Do not output edits for any other node. "
            f"In your response, provide 'curr_patch' for 'curr', and inspect the depth-1 dependents. "
            f"If any dependent needs to be modified next, return its node_id in 'modify_next_nodes'. "
            f"When no more dependents need modification, return an empty list."
        )

        return StepState(
            session_id=session_id,
            curr=curr_slice,
            dependents_depth_1=neighbors,
            pending_queue=session_data.get("pending_queue", []),
            visited_nodes=session_data.get("visited_nodes", []),
            done=False,
            verification_status="IN_PROGRESS",
            instructions=instructions,
        )

    def _slice_node(
        self,
        node: GraphNode,
        direction: str = "current",
        relationship: Optional[str] = None,
    ) -> NodeSlice:
        """Extract exact AST-bounded code text from file."""
        code_text = node.body_source or ""
        file_path = self.repo_path / node.file_path

        if file_path.exists():
            try:
                lines = file_path.read_text(encoding="utf-8").splitlines()
                start = max(0, node.span.start_line - 1)
                end = min(len(lines), node.span.end_line)
                code_text = "\n".join(lines[start:end])
            except Exception:
                pass

        if not code_text.strip():
            code_text = node.canonical_signature()

        return NodeSlice(
            node_id=node.id,
            file_path=node.file_path,
            start_line=node.span.start_line,
            end_line=node.span.end_line,
            name=node.name,
            kind=node.kind.value,
            code=code_text,
            direction=direction,
            relationship=relationship,
        )

    def _finish_session(
        self,
        session_id: str,
        session_data: Dict[str, Any],
        graph: CodeGraph,
        apply: bool,
    ) -> StepState:
        """Construct atomic mutation plan from all stepped patches and verify in sandbox."""
        patches: Dict[str, str] = session_data.get("patches", {})
        visited: List[str] = session_data.get("visited_nodes", [])
        primary_id = visited[0] if visited else list(patches.keys())[0]

        bundled: List[BundledEdit] = []
        for node_id, patch_code in patches.items():
            node = graph.get_node(node_id)
            if node:
                bundled.append(
                    BundledEdit(
                        node_id=node.id,
                        file_path=node.file_path,
                        edit_span=node.span,
                        patch=patch_code,
                        reason=EditReason.TARGET_DEFINITION if node_id == primary_id else EditReason.CROSS_BOUNDARY_CONSUMER,
                        description=f"Stepped mutation for {node.name}",
                    )
                )

        plan = AtomicMutationPlan(
            graph_epoch=graph.graph_epoch,
            target_node=primary_id,
            change_kind=ChangeKind.SEMANTIC_CHANGE,
            bundled_edits=bundled,
            policy_applied=self.blast_engine.compute_blast_radius(graph, primary_id).policy,
        )

        verification = self.sandbox.verify_plan(plan, graph)
        applied = False
        if verification.passed and apply:
            self._apply_plan_to_disk(plan)
            applied = True

        touched = list({e.file_path for e in plan.bundled_edits if e.patch.strip()})

        return StepState(
            session_id=session_id,
            done=True,
            verification_status=plan.status.value,
            applied=applied,
            touched_files=touched,
            diagnostics=verification.diagnostics,
            instructions="All requested links processed. Verification sandbox complete.",
        )

    def _apply_plan_to_disk(self, plan: AtomicMutationPlan) -> None:
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
                    if patch_str and not patch_str.startswith(("# [Harness", "//", "--")):
                        start_idx = max(0, edit.edit_span.start_line - 1)
                        end_idx = min(len(lines), edit.edit_span.end_line)
                        lines = lines[:start_idx] + edit.patch.splitlines() + lines[end_idx:]
                file_path.write_text("\n".join(lines), encoding="utf-8")

    @classmethod
    def _save_session(cls, sess_id: str, data: Dict[str, Any]) -> None:
        cls._sessions[sess_id] = data
        try:
            cache_dir = Path.home() / ".cache" / "debug-harness" / "sessions"
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / f"{sess_id}.json").write_text(json.dumps(data), encoding="utf-8")
        except Exception:
            pass

    @classmethod
    def _load_session(cls, sess_id: str) -> Dict[str, Any]:
        if sess_id in cls._sessions:
            return cls._sessions[sess_id]
        cache_file = Path.home() / ".cache" / "debug-harness" / "sessions" / f"{sess_id}.json"
        if cache_file.exists():
            data = json.loads(cache_file.read_text(encoding="utf-8"))
            cls._sessions[sess_id] = data
            return data
        return {}

    @staticmethod
    def _extract_clean_code(text: str) -> str:
        code = text.strip()
        if "```" in code:
            import re
            m = re.search(r"```(?:[a-zA-Z0-9_-]+)?\s*(.*?)\s*```", code, re.DOTALL)
            if m:
                code = m.group(1)
        return code
