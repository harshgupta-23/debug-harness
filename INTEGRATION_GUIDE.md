# Antigravity (AGY) Integration Guide

Integrate the **Deterministic Code-Graph Harness** directly into **Antigravity (AGY)** as an MCP server directly from GitHub.

**Zero Extra API Keys Required**: The harness extracts deterministic AST code slices and enforces sandbox gates, while AGY synthesizes patches using its existing active model session.

---

## 1. Quick Install via GitHub

Run ephemerally with `uvx`:

```bash
uvx --from git+https://github.com/harshgupta-23/debug-harness.git harness --help
```

Or install globally:

```bash
uv tool install git+https://github.com/harshgupta-23/debug-harness.git
```

---

## 2. AGY MCP Configuration

Add to your Antigravity MCP configuration (`~/.gemini/antigravity/mcp.json` or workspace MCP settings):

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

---

## 3. How AGY Uses the Stepper Tool (`harness_step`)

The harness restricts AGY to **one function at a time**, displaying only the focused node and its immediate 1-hop neighbors:

### Step 1: Initialize Session
AGY invokes:
```json
// Tool: harness_step
{
  "repo_path": "/path/to/project",
  "issue": "Null pointer in discount calculation when discount_rate is None"
}
```

**Harness returns:**
- `curr`:
  - `name`: `compute_total`
  - `file_path`: `routes.py`
  - `start_line`: 15, `end_line`: 19
  - `code`: Exact AST function slice
- `dependents_depth_1`: List of 1-hop upstream (callers) and downstream (callees/endpoints) nodes with the same fields (`name`, `file_path`, `lines`, `code`, `direction`, `relationship`).
- `instructions`: *"Strictly restricted to edit ONLY 'curr'. Provide curr_patch, and specify which dependents need modification next in modify_next_nodes."*

### Step 2: Patch `curr` & Choose Next Link
AGY returns:
```json
// Tool: harness_step
{
  "repo_path": "/path/to/project",
  "session_id": "step_8f075d95",
  "curr_patch": "def compute_total(base_amount: float, discount_rate: float | None = None) -> float:\n    ...",
  "modify_next_nodes": ["fn:routes.py#get_order_details#L23"]
}
```

- The harness securely records the patch for `curr`.
- The harness advances focus to `get_order_details`, loading its AST slice and *its* 1-hop neighborhood.

### Step 3: Complete Traversal
When all required nodes have been visited and patched:
```json
// Tool: harness_step
{
  "repo_path": "/path/to/project",
  "session_id": "step_8f075d95",
  "curr_patch": "def get_order_details(order_id: int) -> dict:\n    ...",
  "modify_next_nodes": [],
  "apply": true
}
```

- The harness runs the multi-stage sandbox verification (in-memory AST overlay + targeted tests).
- If verified, commits all changes atomically to disk.
- Returns `done: true`, `verification_status: "SANDBOX_VERIFIED"`.

---

## 4. Direct Terminal Usage (Optional)

You can also run the stepper manually from your terminal:

```bash
# Start a step session
harness step --repo ./my_project --issue "Fix order discount null error"

# Advance to next node with patch
harness step --repo ./my_project --session "step_8f075d95" --patch "def ..." --next "node_id"
```
