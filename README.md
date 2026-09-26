# Deterministic Code-Graph Debugging & Mutation Harness

[![Repository](https://img.shields.io/badge/GitHub-harshgupta--23%2Fdebug--harness-blue)](https://github.com/harshgupta-23/debug-harness)

A zero-API-key developer engine and CLI that maps codebases into typed AST dependency graphs, resolves single or multi-symptom bug entry points, enforces single-function edit boundaries, and gatekeeps code changes through sandbox verification.

---

## ⚡ Quickstart

```bash
# Direct install from GitHub:
uv tool install git+https://github.com/harshgupta-23/debug-harness.git

# Or install locally in development:
uv pip install -e .

# 1. View codebase outline to find symbol anchors:
harness outline --repo ./my_project

# 2. Step 1 node at a time through the code graph:
harness step --repo ./my_project --issue "Fix order discount calculation" --symptom compute_total

# 3. Handle multiple glitches at once with traversal logging:
harness step --repo ./my_project --symptoms checkout_route --symptoms cart_total --logs run_log.txt
```

---

## 🤖 Using Inside Antigravity (AGY) & MCP Agents

The harness uses an **Inversion-of-Control** protocol. **Zero extra API keys or third-party models are needed** because AGY synthesizes code directly using its own active model connection.

Add to your AGY MCP config (`~/.gemini/antigravity/mcp.json`):
```json
{
  "mcpServers": {
    "debug-harness": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/harshgupta-23/debug-harness.git", "harness", "mcp"]
    }
  }
}
```

### Exposed MCP Tools

1. **`harness_outline`**:
   - `repo_path`: Path to target repository.
   - Returns a compact JSON map of all files and their top-level symbols (functions, classes, endpoints, line ranges).
   
2. **`harness_step`**:
   - `repo_path`: Path to target repository.
   - `session_id`: Omit on first call to initialize; provide on subsequent calls.
   - `issue`: Problem or bug description.
   - `symptom`: Optional single function or anchor name.
   - `symptoms`: Optional list of multiple symptom symbol names.
     - **Shared Root**: If symptoms share common upstream callers or downstream callees, collapses to 1 shared root cause.
     - **Disjoint**: If symptoms are independent, queues them sequentially.
   - `curr_patch`: Replacement code for `curr` ONLY (**Strict Restriction**).
   - `modify_next_nodes`: List of depth-1 neighbor node IDs that need editing next.
   - `apply`: Verify in sandbox and write to disk when all links return empty (`default: true`).

3. **`harness_blast_radius`**:
   - `repo_path`: Path to target repository.
   - `node_id`: Target symbol ID.
   - Returns reachability analysis and cross-boundary safety policies.

---

## 🛠️ CLI Reference

```bash
# Display compact symbol outline:
harness outline --repo ./my_project

# Single-symptom step session:
harness step --repo ./my_project --symptom compute_total

# Multi-symptom with terminal logs:
harness step --repo ./my_project --symptoms route_a --symptoms route_b --logs

# Multi-symptom saving logs to .txt:
harness step --repo ./my_project --symptoms route_a --symptoms route_b --logs debug.txt

# Inspect session traversal logs anytime:
harness logs <session_id> [--output debug.txt]

# Compute blast radius for a symbol:
harness blast-radius --repo ./my_project --node "fn:routes.py#compute_total#L15"

# Deterministically index repository:
harness index --repo ./my_project
```
