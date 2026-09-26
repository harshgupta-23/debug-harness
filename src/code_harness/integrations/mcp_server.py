"""Standard Model Context Protocol (MCP) stdio server for external agent integration.

Allows tools like Antigravity (AGY), Claude Code, Cursor, and OpenHands to invoke the harness.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict

from code_harness.harness import Harness


TOOLS = [
    {
        "name": "harness_fix",
        "description": "Fix a bug in a codebase using deterministic AST graph traversal, blast-radius locking, and sandbox verification.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Absolute path to repository directory."},
                "issue": {"type": "string", "description": "Description of bug or error to fix."},
                "apply": {"type": "boolean", "description": "Whether to write verified fix directly to disk.", "default": False},
                "use_harness": {"type": "boolean", "description": "Toggle harness on (deterministic parser) or off (baseline).", "default": True},
            },
            "required": ["repo_path", "issue"],
        },
    },
    {
        "name": "harness_blast_radius",
        "description": "Compute reachability and cross-boundary dependents (DB ↔ Backend ↔ Frontend) for a symbol.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "repo_path": {"type": "string", "description": "Path to repository."},
                "node_id": {"type": "string", "description": "Target symbol or node ID (e.g. fn:routes.py#compute_total)."},
            },
            "required": ["repo_path", "node_id"],
        },
    },
]


def run_stdio_mcp() -> None:
    """Run JSON-RPC 2.0 stdio loop for MCP clients."""
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
            arguments = params.get("arguments", {})

            try:
                if tool_name == "harness_fix":
                    harness = Harness(
                        repo_path=arguments.get("repo_path", "."),
                        use_harness=arguments.get("use_harness", True),
                    )
                    res = harness.fix(
                        issue=arguments.get("issue", ""),
                        apply=arguments.get("apply", False),
                    )
                    content = res.model_dump_json(indent=2)
                elif tool_name == "harness_blast_radius":
                    harness = Harness(repo_path=arguments.get("repo_path", "."))
                    graph = harness.indexer.index()
                    report = harness.blast_engine.compute_blast_radius(
                        graph, arguments.get("node_id", "")
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
                    "serverInfo": {"name": "code-harness-mcp", "version": "0.2.0"},
                },
            }
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()
