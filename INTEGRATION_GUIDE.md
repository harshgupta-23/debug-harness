# Antigravity (AGY) Integration Guide

Integrate the **Deterministic Code-Graph Harness** directly into **Antigravity (AGY)** as an MCP server directly from GitHub.

**Zero Extra API Keys Required**: The harness uses an Inversion-of-Control protocol. It extracts the deterministic context and verifies patches in a sandbox, while AGY synthesizes the code using its own active model session.

---

## 1. Quick Install via GitHub

Run ephemerally with `uvx` (zero pre-install required):

```bash
uvx --from git+https://github.com/harshgupta-23/debug-harness.git harness --help
```

Or install globally:

```bash
uv tool install git+https://github.com/harshgupta-23/debug-harness.git
```

---

## 2. AGY MCP Configuration

Add the harness to your Antigravity MCP configuration (`~/.gemini/antigravity/mcp.json` or workspace MCP settings):

```json
{
  "mcpServers": {
    "debug-harness": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/harshgupta-23/debug-harness.git",
        "harness",
        "mcp"
      ]
    }
  }
}
```

*Note: No `env` or `API_KEY` is required because AGY performs the generation using its own model connection.*

---

## 3. How AGY Uses the Harness (Two-Phase Protocol)

When pair-programming with AGY, ask:
> *"Use the debug-harness to fix the null pointer issue in the orders API."*

### Phase 1: Context Preparation & Contract Locking
AGY invokes:
```json
// Tool: harness_prepare
{
  "repo_path": "/path/to/project",
  "issue": "Null pointer in discount calculation when discount_rate is None"
}
```
**Harness returns:**
- `plan_id`: Unique identifier (e.g. `amp_8c41f92e`).
- `target_node`: Exact function to edit (`fn:routes.py#compute_total`).
- `locked_dependents`: All cross-boundary dependents that must be updated together (e.g. `client.js`, `models.py`).
- `context_stack`: Field-level projected slices (< 1,500 tokens). AGY does not search the codebase or read whole files.

### Phase 2: Sandbox Verification & Atomic Commit
AGY writes the clean patch using its own model session and submits it:
```json
// Tool: harness_verify_and_apply
{
  "repo_path": "/path/to/project",
  "plan_id": "amp_8c41f92e",
  "target_patch": "def compute_total(base_amount: float, discount_rate: float | None = None) -> float:\n    ...",
  "apply": true
}
```
**Harness executes:**
1. Applies patch to an in-memory overlay (zero premature disk writes).
2. Runs AST syntax & diagnostic check.
3. Queries call graph for tests reaching modified nodes and runs them (`pytest`).
4. If verified, commits changes to disk and returns `SANDBOX_VERIFIED`. If broken, returns compiler/test diagnostics for AGY to self-correct.

---

## 4. Direct Terminal Usage (Optional)

Developers can also run the two phases manually in terminal:

```bash
# Phase 1: Prepare context & lock contract
harness prepare --repo ./my_project --issue "Fix order discount null error"

# Phase 2: Verify & apply proposed patch
harness verify --repo ./my_project --plan-id "amp_8c41f92e" --patch ./fix.py --apply

# Or standalone one-shot run:
harness fix --repo ./my_project --issue "Fix order discount null error" --apply
```
