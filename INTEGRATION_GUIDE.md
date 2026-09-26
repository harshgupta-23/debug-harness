# Antigravity (AGY) Integration Guide

Integrate the **Deterministic Code-Graph Harness** directly into **Antigravity (AGY)** as a Model Context Protocol (MCP) server directly from GitHub.

---

## 1. Quick Install via GitHub

No local cloning needed. AGY can invoke the harness using `uvx` or a global `uv tool` install:

```bash
# Global CLI installation
uv tool install git+https://github.com/harshgupta-23/debug-harness.git

# Or run ephemerally with uvx (zero pre-install required)
uvx --from git+https://github.com/harshgupta-23/debug-harness.git harness --help
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
      ],
      "env": {
        "GEMINI_API_KEY": "${GEMINI_API_KEY}"
      }
    }
  }
}
```

Once added, AGY automatically gains two deterministic tools:
- **`harness_fix`**: Analyzes the issue, indexes the AST graph, locks cross-boundary dependents (DB ↔ Backend ↔ Frontend), calls Gemini with a bounded Context Stack, verifies the patch in a sandbox, and applies it.
- **`harness_blast_radius`**: Inspects all direct, transitive, and cross-boundary callers and dependents of any symbol.

---

## 3. Model & API Key Configuration

The harness uses **Google Gemini** as its standard model (matching AGY's native runtime).

- **API Key**: Ensure `GEMINI_API_KEY` is set in your environment:
  ```bash
  export GEMINI_API_KEY="AIza..."
  ```
- **Default Model**: `gemini-1.5-flash` (fast, sub-second synthesis).
- To override the model for high-complexity architectural changes, pass `--model`:
  ```bash
  harness fix --repo /path/to/project --issue "Fix schema drift" --model "gemini-1.5-pro"
  ```

---

## 4. How AGY Invokes the Harness

When pair-programming with AGY, simply ask:
> *"Use the debug-harness to fix the null pointer issue in the orders API and apply it."*

AGY calls `harness_fix`:
```json
{
  "repo_path": "/home/hp/projects/my-app",
  "issue": "Null pointer in discount calculation when discount_rate is None",
  "apply": true,
  "use_harness": true
}
```

### The Toggle (`use_harness`):
- **`use_harness: true` (Default)**: Full deterministic pipeline — AST indexer, System-1 edge scoring, blast radius locking, and sandbox verification.
- **`use_harness: false`**: Standard baseline agent mode without the graph parser or sandbox gate (records telemetry parameters only).

---

## 5. Direct Terminal Usage (Optional)

You can also run the harness directly from your terminal:

```bash
# Analyze and verify patch (dry run)
harness fix --repo /path/to/project --issue "Fix order discount error"

# Apply verified patch to files
harness fix --repo /path/to/project --issue "Fix order discount error" --apply

# Trace reachability & cross-boundary dependencies
harness blast-radius --repo /path/to/project --node "fn:routes.py#compute_total"
```
