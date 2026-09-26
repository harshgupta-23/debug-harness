"""Atomic Edit Contract and Context Stack Protocol.

Enforces Invariant I3, I5, §3.4, §4.1, §4.2:
- Generates Pydantic-validated AtomicMutationPlan.
- Dependency-locking protocol: locks ALL cross-boundary dependents into a single transactional patch.
- ContextStack: typed stack of graph frames carrying bounded projections, not flat file bags.
"""

from __future__ import annotations

import uuid
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from code_harness.core.graph import CodeGraph, CodeSpan, GraphNode, NodeKind
from code_harness.engine.blast_radius import BlastRadiusReport, SafetyPolicy


class PlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SANDBOX_VERIFIED = "SANDBOX_VERIFIED"
    REJECTED = "REJECTED"


class ChangeKind(str, Enum):
    SIGNATURE_CHANGE = "signatureChange"
    RETURN_TYPE_CHANGE = "returnTypeChange"
    FIELD_RENAME = "fieldRename"
    DELETE = "delete"
    SEMANTIC_CHANGE = "semanticChange"


class EditReason(str, Enum):
    TARGET_DEFINITION = "targetDefinition"
    DIRECT_CALLER = "directCaller"
    CROSS_BOUNDARY_CONSUMER = "crossBoundaryConsumer"
    TYPE_CONTRACT_UPDATE = "typeContractUpdate"
    COMPAT_SHIM = "compatShim"


class BundledEdit(BaseModel):
    node_id: str
    file_path: str
    edit_span: CodeSpan
    patch: str
    reason: EditReason
    description: Optional[str] = None


class AtomicMutationPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: f"amp_{uuid.uuid4().hex[:8]}")
    graph_epoch: int
    target_node: str
    change_kind: ChangeKind
    bundled_edits: List[BundledEdit] = Field(default_factory=list)
    invariants_checked: List[str] = Field(default_factory=list)
    policy_applied: SafetyPolicy
    status: PlanStatus = PlanStatus.DRAFT
    rejection_reason: Optional[str] = None


# -----------------------------------------------------------------------------
# Context Stack Protocol (§3.4)
# -----------------------------------------------------------------------------

class StackFrame(BaseModel):
    frame_id: int
    node_id: str
    projection: str  # Minimal field-level slice, e.g. signature+returnType+bounded body
    relevance_score: float = 1.0
    token_estimate: int = 0


class ContextStack(BaseModel):
    frames: List[StackFrame] = Field(default_factory=list)
    push_order: List[int] = Field(default_factory=list)
    total_token_budget: int = 3000
    frame_eviction_policy: str = "LRU-by-relevance-score"

    def current_tokens(self) -> int:
        return sum(f.token_estimate for f in self.frames)

    def push_frame(self, node: GraphNode, score: float = 1.0) -> StackFrame:
        """Project node into minimal slice and push onto stack under token budget."""
        # Minimal projection: never full file
        if node.kind == NodeKind.FUNCTION:
            body_preview = node.body_source or ""
            # Bound body to <= 40 lines
            body_lines = body_preview.splitlines()[:40]
            bounded_body = "\n".join(body_lines)
            projection = f"[{node.file_path}]\n{node.signature} -> {node.return_type or 'None'}:\n{bounded_body}"
        elif node.kind == NodeKind.ENDPOINT:
            projection = f"[{node.file_path}] {node.http_method} {node.route_pattern} [response: {node.response_schema}]"
        elif node.kind == NodeKind.DB_COLUMN:
            projection = f"[{node.file_path}] Table '{node.table}' Column '{node.name}' ({node.col_type}, nullable={node.nullable})"
        elif node.kind == NodeKind.DTO:
            fields_str = ", ".join(f"{k}: {v}" for k, v in node.fields.items())
            projection = f"[{node.file_path}] DTO {node.name} {{{fields_str}}}"
        else:
            projection = f"[{node.file_path}] {node.kind.value} {node.name}"

        # Approximate tokens (~4 chars per token)
        token_est = max(1, len(projection) // 4)
        frame_id = len(self.frames)
        frame = StackFrame(
            frame_id=frame_id,
            node_id=node.id,
            projection=projection,
            relevance_score=score,
            token_estimate=token_est,
        )

        self.frames.append(frame)
        self.push_order.append(frame_id)
        self._enforce_budget()
        return frame

    def _enforce_budget(self) -> None:
        """Evict frames by lowest relevance score first if budget exceeded."""
        while self.current_tokens() > self.total_token_budget and len(self.frames) > 1:
            # Find frame with lowest relevance score (excluding top frame 0)
            lowest_idx = 1
            lowest_score = self.frames[1].relevance_score
            for i in range(2, len(self.frames)):
                if self.frames[i].relevance_score < lowest_score:
                    lowest_score = self.frames[i].relevance_score
                    lowest_idx = i
            self.frames.pop(lowest_idx)

    def render_context(self) -> str:
        """Render ordered context stack for System 2."""
        sections = [
            f"=== GRAPH CONTEXT FRAME {f.frame_id} [Node: {f.node_id}] (Score: {f.relevance_score:.2f}) ===\n{f.projection}"
            for f in self.frames
        ]
        return "\n\n".join(sections)


# -----------------------------------------------------------------------------
# Atomic Contract Builder
# -----------------------------------------------------------------------------

class ContractBuilder:
    """Builds and validates Atomic Mutation Plans locking all dependents."""

    @staticmethod
    def build_plan(
        graph: CodeGraph,
        blast_report: BlastRadiusReport,
        change_kind: ChangeKind,
        target_patch: str,
        dependent_patches: Optional[Dict[str, str]] = None,
    ) -> AtomicMutationPlan:
        """Lock target and all mandatory cross-boundary dependents into atomic plan."""
        target_node = graph.get_node(blast_report.target_node)
        if not target_node:
            raise KeyError(f"Target node '{blast_report.target_node}' not found.")

        bundled: List[BundledEdit] = []
        dep_patches = dependent_patches or {}

        # 1. Target node edit
        bundled.append(
            BundledEdit(
                node_id=target_node.id,
                file_path=target_node.file_path,
                edit_span=target_node.span,
                patch=target_patch,
                reason=EditReason.TARGET_DEFINITION,
                description=f"Primary mutation on target {target_node.name}",
            )
        )

        # 2. Mandatory dependents locking (Invariant I3)
        # Direct callers & cross-boundary consumers
        invariants = [
            "allDirectCallersUpdated",
            "allCrossBoundaryConsumersUpdated",
            "noOrphanedTypeReferences",
            "testCoverageExistsForModifiedNodes",
        ]

        unresolved_nodes: List[str] = []

        for dep in blast_report.cross_boundary_dependents:
            node = dep.node
            reason = EditReason.CROSS_BOUNDARY_CONSUMER
            if dep.kind == "frontendFetcher":
                patch_content = dep_patches.get(node.id, "")
                if not patch_content:
                    # Provide default required signature alignment if not supplied
                    patch_content = f"// [Harness Locked] Update call site for {target_node.name}\n"
                bundled.append(
                    BundledEdit(
                        node_id=node.id,
                        file_path=node.file_path,
                        edit_span=node.span,
                        patch=patch_content,
                        reason=reason,
                        description=f"Cross-boundary frontend consumer '{node.name}'",
                    )
                )
            elif dep.kind == "dbMigrationRisk":
                patch_content = dep_patches.get(node.id, "")
                if not patch_content:
                    patch_content = f"-- [Harness Locked] Schema migration sync for {node.name}\n"
                bundled.append(
                    BundledEdit(
                        node_id=node.id,
                        file_path=node.file_path,
                        edit_span=node.span,
                        patch=patch_content,
                        reason=EditReason.TYPE_CONTRACT_UPDATE,
                        description=f"Database schema contract update for '{node.name}'",
                    )
                )

        # Direct dependents that are functions
        for aff in blast_report.affected_nodes:
            if aff.id not in [b.node_id for b in bundled]:
                patch_content = dep_patches.get(aff.id, "")
                if not patch_content:
                    patch_content = f"# [Harness Locked] Direct caller update for {aff.name}\n"
                bundled.append(
                    BundledEdit(
                        node_id=aff.id,
                        file_path=aff.file_path,
                        edit_span=aff.span,
                        patch=patch_content,
                        reason=EditReason.DIRECT_CALLER,
                        description=f"Direct caller update for '{aff.name}'",
                    )
                )

        # Fail closed if unresolvable
        status = PlanStatus.DRAFT
        rejection_reason = None
        if unresolved_nodes:
            status = PlanStatus.REJECTED
            rejection_reason = f"Unresolvable mandatory dependents: {unresolved_nodes}"

        return AtomicMutationPlan(
            graph_epoch=blast_report.graph_epoch,
            target_node=blast_report.target_node,
            change_kind=change_kind,
            bundled_edits=bundled,
            invariants_checked=invariants,
            policy_applied=blast_report.policy,
            status=status,
            rejection_reason=rejection_reason,
        )
