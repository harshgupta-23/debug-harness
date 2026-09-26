# Deterministic Code-Graph Debugging & Mutation Harness

[![Repository](https://img.shields.io/badge/GitHub-harshgupta--23%2Fdebug--harness-blue)](https://github.com/harshgupta-23/debug-harness)

A developer engine and CLI that analyzes codebases, locks cross-boundary dependencies into atomic mutation plans, and verifies bug fixes using deterministic AST graphs and sandbox execution.

---

## ⚡ Quickstart

```bash
# Direct install from GitHub:
uv tool install git+https://github.com/harshgupta-23/debug-harness.git

# Or install locally in development:
uv pip install -e .

# Point to your project folder and fix a bug:
harness fix --repo /path/to/project --issue "Fix NoneType error in calculate_total" --apply
```

---

## 🎛️ Toggle: Harness vs Baseline Mode

- **Toggle ON (Default)**: Full deterministic pipeline — AST indexing, System 1 candidate scoring, blast-radius cross-boundary locking (DB ↔ Backend ↔ Frontend), scoped Context Stack, and 3-stage Sandbox verification before applying.
  ```bash
  harness fix --repo /path/to/project --issue "Fix error" --harness
  ```
- **Toggle OFF**: Raw baseline agent mode without the graph parser or sandbox gate (records telemetry parameters only).
  ```bash
  harness fix --repo /path/to/project --issue "Fix error" --no-harness
  ```

---

## 🤖 Using Inside Antigravity (AGY) & Other Agents

The harness uses an **Inversion-of-Control** protocol. **Zero extra API keys are needed** because AGY uses its own active model session to generate the code.

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

### Two-Phase Agent Protocol
1. **`harness_prepare(repo_path, issue)`**: Deterministically builds the call-graph, locks all cross-boundary dependents (DB ↔ Backend ↔ Frontend), and returns a bounded `<1,500` token Context Stack.
2. **`harness_verify_and_apply(repo_path, plan_id, target_patch, apply)`**: Verification sandbox gate. Runs AST syntax validation and targeted `pytest` tests before committing edits to disk.

---

## 🛠️ Additional Commands
```bash
# Inspect graph nodes and edges
harness index --repo ./my_project

# Trace root cause candidates
harness trace --repo ./my_project --symptom "fn:routes.py#compute_total"

# Calculate blast radius & cross-boundary dependents
harness blast-radius --repo ./my_project --node "fn:routes.py#compute_total"
```
