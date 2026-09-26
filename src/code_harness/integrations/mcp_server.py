"""Standard Model Context Protocol (MCP) stdio server for AGY.

Enforces zero-API-key Inversion of Control:
1. harness_prepare: Provides deterministic ContextStack and locks Atomic Contract.
2. harness_verify_and_apply: Runs sandbox verification gate on AGY's proposed patch.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from code_harness.harness import Harness


TOOLS = [
    {
        "name": "harness_prepare",
        "description": "Deterministically index repository, lock cross-boundary dependents, and return a bounded Context Stack for an issue. Zero extra API keys needed.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to target repository folder."},
                "issue": {"type": "string", "description": "Error message, test failure, or bug description."},
                "symptom": {"type": "string", "description": "Optional function name or file:line anchor."},
            },
            "required": ["repo_path", "issue"],
        },
    },
    {
        "name": "harness_verify_and_apply",
        "description": "Verification sandbox gate: test model-authored diff against AST syntax and graph-targeted tests before applying.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to target repository folder."},
                "plan_id": {"type": "string", "description": "Plan ID returned by harness_prepare."},
                "target_patch": {"type": "string", "description": "Clean replacement code for the target function."},
                "dependent_patches": {"type": "object", "description": "Optional mapping of dependent node ID to replacement code."},
                "apply": {"type": "boolean", "description": "Write verified changes directly to files if passed.", "default": True},
            },
            "required": ["repo_path", "plan_id", "target_patch"],
        },
    },
    {
        "name": "harness_blast_radius",
        "description": "Inspect reachability, cross-boundary dependents (DB ↔ Backend ↔ Frontend), and safety policy for any symbol.",
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


# Persistent harness instances per repo
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

                if tool_name == "harness_prepare":
                    res = harness.prepare(
                        issue=args.get("issue", ""),
                        symptom_node=args.get("symptom"),
                    )
                    content = res.model_dump_json(indent=2)

                elif tool_name == "harness_verify_and_apply":
                    res = harness.verify_and_apply(
                        plan_id=args.get("plan_id", ""),
                        target_patch=args.get("target_patch", ""),
                        dependent_patches=args.get("dependent_patches"),
                        apply=args.get("apply", True),
                    )
                    content = res.model_dump_json(indent=2)

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
