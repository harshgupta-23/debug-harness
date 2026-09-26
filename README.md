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

## 🔑 Setting API Key & Model

Set standard environment variables in your terminal or `.env`:
```bash
# For Gemini
export GEMINI_API_KEY="AIza..."

# Or for OpenAI / compatible providers
export OPENAI_API_KEY="sk-..."
export OPENAI_BASE_URL="https://api.openai.com/v1"
```
Or specify the model on the fly:
```bash
harness fix --repo ./my_project --issue "Fix bug" --model "gemini-1.5-flash"
```

---

## 🤖 Using Inside Antigravity (AGY) & Other Agents

### Option 1: Python SDK (Direct Import)
```python
from code_harness import Harness

harness = Harness(repo_path="./my_project", use_harness=True)
result = harness.fix(issue="Fix discount null pointer", apply=True)

print(result.verification_status)  # "SANDBOX_VERIFIED"
print(result.metrics)              # Tokens, latency, calls
```

### Option 2: Model Context Protocol (MCP) Server
Launch the stdio MCP server for AGY, Cursor, Claude Code, or OpenHands:
```bash
harness mcp
```
Configure in your agent's MCP settings (`mcp.json`):
```json
{
  "mcpServers": {
    "code-harness": {
      "command": "harness",
      "args": ["mcp"]
    }
  }
}
```
Exposes tools:
- `harness_fix(repo_path, issue, apply, use_harness)`
- `harness_blast_radius(repo_path, node_id)`

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
