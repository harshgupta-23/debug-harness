"""Standard Model Context Protocol (MCP) stdio server for AGY.

Provides the 1-node-at-a-time graph traversal stepper tool:
- harness_step: inspects 'curr' + depth-1 upstream/downstream neighbors, enforces single-function edit boundary,
  and steps along chosen links until all are resolved.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from code_harness.harness import Harness


TOOLS = [
    {
        "name": "harness_outline",
        "description": "debug-harness: Inspect concise codebase outline of all files, functions, classes, and endpoints to locate starting symptoms.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to target repository folder."},
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "harness_step",
        "description": (
            "debug-harness stepper: Deterministic code-graph debugging tool. "
            "Step through code graph 1 node at a time. Returns 'curr' (file, lines, symbol, exact AST code) "
            "and depth-1 upstream/downstream dependents. STRICT RESTRICTION: You may only modify 'curr'. "
            "Pass 'curr_patch' to edit curr, and pass 'modify_next_nodes' with neighbor IDs that need editing next. "
            "Continues until no more nodes are queued."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to target repository folder."},
                "session_id": {"type": "string", "description": "Session ID (omit on first call to start)."},
                "issue": {"type": "string", "description": "Bug or problem description (used on first call)."},
                "symptom": {"type": "string", "description": "Optional single function name or file:line anchor."},
                "symptoms": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional list of multiple symptom anchors (computes shared root cause or queues disjoint bugs).",
                },
                "curr_patch": {"type": "string", "description": "Replacement code for 'curr' ONLY."},
                "modify_next_nodes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of neighbor node IDs that must be modified next.",
                },
                "apply": {"type": "boolean", "description": "Write verified changes to disk when done.", "default": True},
            },
            "required": ["repo_path"],
        },
    },
    {
        "name": "harness_blast_radius",
        "description": "Inspect reachability and cross-boundary dependents for any symbol.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to target repository folder."},
                "node_id": {"type": "string", "description": "Symbol or node ID (e.g. fn:routes.py#compute_total)."},
            },
            "required": ["repo_path", "node_id"],
        },
    },
]

_HARNESS_CACHE: Dict[str, Harness] = {}


def get_harness(repo_path: str) -> Harness:
    p = str(Path(repo_path).resolve())
    if p not in _HARNESS_CACHE:
        _HARNESS_CACHE[p] = Harness(repo_path=p)
    return _HARNESS_CACHE[p]


def run_stdio_mcp() -> None:
    """Run JSON-RPC 2.0 stdio server loop."""
    for line in sys.stdin:
        if not line.strip():
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params", {})

        if method == "tools/list":
            resp = {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif method == "tools/call":
            tool_name = params.get("name")
            args = params.get("arguments", {})

            try:
                repo_path = args.get("repo_path", ".")
                harness = get_harness(repo_path)

                if tool_name == "harness_outline":
                    outline = harness.get_outline()
                    content = json.dumps(outline, indent=2)

                elif tool_name in ("harness_step", "debug_harness", "debug-harness"):
                    state = harness.step(
                        session_id=args.get("session_id"),
                        issue=args.get("issue"),
                        symptom=args.get("symptom"),
                        symptoms=args.get("symptoms"),
                        curr_patch=args.get("curr_patch"),
                        modify_next_nodes=args.get("modify_next_nodes"),
                        apply=args.get("apply", True),
                    )
                    content = state.model_dump_json(indent=2)

                elif tool_name == "harness_blast_radius":
                    graph = harness.ensure_indexed()
                    report = harness.blast_engine.compute_blast_radius(
                        graph, args.get("node_id", "")
                    )
                    content = report.model_dump_json(indent=2)
                else:
                    content = f"Unknown tool: {tool_name}"

                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": content}]},
                }
            except Exception as e:
                resp = {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32000, "message": str(e)},
                }

            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()

        elif method == "initialize":
            resp = {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "debug-harness-mcp", "version": "0.1.0"},
                },
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
