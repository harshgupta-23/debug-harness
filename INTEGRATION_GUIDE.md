# Antigravity (AGY) Integration Guide

Integrate the **Deterministic Code-Graph Harness** directly into **Antigravity (AGY)** as an MCP server directly from GitHub.

**Zero Extra API Keys Required**: The harness extracts deterministic AST code slices, prunes context, and enforces sandbox gates, while AGY synthesizes patches using its existing active model session.

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

## 3. Workflow: How AGY Interacts with the Harness

### Step 0: Inspect Symbol Outline (Optional)
When AGY needs to map user complaints to exact codebase symbols:
```json
// Tool: harness_outline
{
  "repo_path": "/path/to/project"
}
```
Returns a compact mapping of files to functions, classes, and routes.

---

### Step 1: Initialize Session with 1..N Symptoms
AGY can pass a single issue or multiple symptom symbols reported by the user:

```json
// Tool: harness_step
{
  "repo_path": "/path/to/project",
  "issue": "Prices mismatch and checkout validation fails",
  "symptoms": ["get_order_details", "checkout_route"]
}
```

**Harness Resolution:**
* **Shared Root Cause**: Computes $\bigcap \text{Upstream/Downstream}$. If symptoms share a dependency (e.g., `compute_total`), the harness collapses them and sets `curr` to the common root cause.
* **Disjoint Bugs**: If symptoms have no shared paths, sets `curr` to the first symptom and queues the remaining symptoms in `pending_queue`.

**Harness returns:**
* `curr`:
  * `name`: `compute_total`
  * `file_path`: `routes.py`
  * `start_line`: 15, `end_line`: 19
  * `code`: Exact AST function slice
* `dependents_depth_1`: 1-hop upstream (callers) and downstream (callees/endpoints) nodes with exact slices.
* `instructions`: *"Strictly restricted to edit ONLY 'curr'. Provide curr_patch, and specify which dependents need modification next in modify_next_nodes."*

---

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

* The harness records the patch for `curr`.
* Focus shifts to `get_order_details`, loading its AST slice and *its* 1-hop neighborhood.

---

### Step 3: Complete Traversal & Verify
When all required nodes have been stepped and patched:
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

* Harness executes multi-stage sandbox verification (in-memory AST overlay + targeted pytest execution).
* If verified, commits all changes atomically to disk.
* Returns `done: true`, `verification_status: "SANDBOX_VERIFIED"`.

---

## 4. CLI Traversal Logs

Inspect the entire trajectory of bugs, starting nodes, and step-by-step traversal:

```bash
# Dump traversal log to terminal:
harness step --repo ./my_project --symptoms route_a --symptoms route_b --logs

# Save traversal log to a text file:
harness step --repo ./my_project --symptoms route_a --symptoms route_b --logs traversal.txt

# View logs for any past session:
harness logs <session_id> [--output traversal.txt]
```
