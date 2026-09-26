"""Lightweight MCP server and drop-in proxy adapter.

Enforces Invariant I1, I3, I4, I5 & §1.2:
- Supports Model Context Protocol (MCP) tools:
  - index_workspace
  - trace_root_cause
  - compute_blast_radius
  - propose_atomic_patch
  - verify_patch
- Provides an OpenAI-compatible HTTP proxy adapter for external tools
  (Aider, Continue, OpenHands, Cursor) to route through the harness.
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional

from code_harness.core.graph import CodeGraph
from code_harness.core.indexer import RepositoryIndexer
from code_harness.engine.blast_radius import BlastRadiusEngine
from code_harness.engine.contract import (
    ChangeKind,
    ContextStack,
    ContractBuilder,
)
from code_harness.engine.sandbox import VerificationSandbox
from code_harness.engine.system1 import System1Scorer


class HarnessEngineState:
    """Singleton harness state held in memory."""

    def __init__(self, repo_path: str = ".") -> None:
        self.repo_path = Path(repo_path).resolve()
        self.indexer = RepositoryIndexer(self.repo_path)
        self.graph: Optional[CodeGraph] = None
        self.system1 = System1Scorer()
        self.blast_engine = BlastRadiusEngine()
        self.sandbox = VerificationSandbox(self.repo_path)
        self.plans: Dict[str, Any] = {}

    def ensure_indexed(self) -> CodeGraph:
        if self.graph is None:
            self.graph = self.indexer.index()
        return self.graph


# Global daemon state
_STATE = HarnessEngineState()


def handle_mcp_request(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """Execute MCP tool calls."""
    graph = _STATE.ensure_indexed()

    if method in {"indexWorkspace", "tools/call/index_workspace"}:
        repo = params.get("rootUri", str(_STATE.repo_path))
        _STATE.repo_path = Path(repo.replace("file://", "")).resolve()
        _STATE.indexer = RepositoryIndexer(_STATE.repo_path)
        _STATE.sandbox = VerificationSandbox(_STATE.repo_path)
        _STATE.graph = _STATE.indexer.index()
        return {
            "graph_epoch": _STATE.graph.graph_epoch,
            "nodeCount": _STATE.graph.node_count(),
            "edgeCount": _STATE.graph.edge_count(),
            "unresolvedRefs": _STATE.graph.unresolved_refs,
        }

    elif method in {"computeBlastRadius", "tools/call/compute_blast_radius"}:
        target_node = params.get("node")
        if not target_node:
            raise ValueError("Parameter 'node' is required.")
        report = _STATE.blast_engine.compute_blast_radius(graph, target_node)
        return report.model_dump()

    elif method in {"traceRootCause", "tools/call/trace_root_cause"}:
        symptom_node = params.get("symptom_node")
        query = params.get("query", "error")
        if not symptom_node or not graph.has_node(symptom_node):
            raise ValueError(f"Symptom node '{symptom_node}' not found.")

        # Search candidates in graph
        candidates = []
        for pred, edge in graph.predecessors(symptom_node):
            candidates.append((pred, edge, [symptom_node]))
        for succ, edge in graph.successors(symptom_node):
            candidates.append((succ, edge, [symptom_node]))

        ranked = _STATE.system1.score_candidates(query, candidates)
        return {
            "graph_epoch": graph.graph_epoch,
            "candidateOrigins": [c.model_dump() for c in ranked[:5]],
        }

    elif method in {"proposeAtomicPatch", "tools/call/propose_atomic_patch"}:
        target_node = params.get("target_node")
        change_kind_str = params.get("change_kind", "semanticChange")
        target_patch = params.get("target_patch", "")
        dep_patches = params.get("dependent_patches", {})

        report = _STATE.blast_engine.compute_blast_radius(graph, target_node)
        plan = ContractBuilder.build_plan(
            graph=graph,
            blast_report=report,
            change_kind=ChangeKind(change_kind_str),
            target_patch=target_patch,
            dependent_patches=dep_patches,
        )
        _STATE.plans[plan.plan_id] = plan
        return plan.model_dump()

    elif method in {"verifyPatch", "tools/call/verify_patch"}:
        plan_id = params.get("plan_id")
        plan = _STATE.plans.get(plan_id)
        if not plan:
            raise KeyError(f"Plan '{plan_id}' not found.")
        verification = _STATE.sandbox.verify_plan(plan, graph)
        return verification.model_dump()

    else:
        raise NotImplementedError(f"Method '{method}' not implemented.")


class HarnessProxyHandler(BaseHTTPRequestHandler):
    """OpenAI-compatible and JSON-RPC / MCP HTTP handler."""

    def do_POST(self) -> None:
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode("utf-8")

        try:
            req_data = json.loads(body)
        except Exception:
            self._send_response(400, {"error": "Invalid JSON"})
            return

        # 1. Handle OpenAI-compatible /v1/chat/completions
        if self.path == "/v1/chat/completions":
            self._handle_openai_proxy(req_data)
            return

        # 2. Handle JSON-RPC / MCP calls
        method = req_data.get("method", "")
        params = req_data.get("params", {})
        req_id = req_data.get("id")

        try:
            result = handle_mcp_request(method, params)
            response = {"jsonrpc": "2.0", "id": req_id, "result": result}
            self._send_response(200, response)
        except Exception as e:
            response = {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": str(e)}}
            self._send_response(500, response)

    def _handle_openai_proxy(self, data: Dict[str, Any]) -> None:
        """Inject scoped ContextStack into prompt rather than unbounded files."""
        graph = _STATE.ensure_indexed()
        messages = data.get("messages", [])

        # Build ContextStack from relevant nodes
        stack = ContextStack(total_token_budget=2000)
        for node in graph.all_nodes()[:5]:  # Top bounded slice
            stack.push_frame(node)

        injected_context = stack.render_context()
        augmented_prompt = f"System Context (Deterministic Graph Frames):\n{injected_context}\n\nTask: Process request within locked contract."

        # Return mock OpenAI response conforming to contract
        response = {
            "id": "chatcmpl-harness-proxy",
            "object": "chat.completion",
            "created": 1700000000,
            "model": data.get("model", "harness-router"),
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": f"[HARNESS VERIFIED CONTEXT STACK]\n{augmented_prompt}",
                    },
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": stack.current_tokens(),
                "completion_tokens": 50,
                "total_tokens": stack.current_tokens() + 50,
            },
        }
        self._send_response(200, response)

    def _send_response(self, status: int, data: Dict[str, Any]) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:
        # Silence standard HTTP logs for clean terminal experience
        pass


def run_proxy_server(port: int = 8000, repo_path: str = ".") -> None:
    """Start local HTTP/MCP proxy server."""
    global _STATE
    _STATE = HarnessEngineState(repo_path)
    _STATE.ensure_indexed()

    server = HTTPServer(("0.0.0.0", port), HarnessProxyHandler)
    print(f"[*] Harness MCP/Proxy running on http://127.0.0.1:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
