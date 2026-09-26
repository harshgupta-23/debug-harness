# Deterministic Code-Graph Debugging & Mutation Harness

[![Repository](https://img.shields.io/badge/GitHub-harshgupta--23%2Fdebug--harness-blue)](https://github.com/harshgupta-23/debug-harness)

A zero-API-key developer harness that maps codebases into typed AST dependency graphs, resolves bug entry points, enforces single-function edit boundaries, and gatekeeps code changes with sandbox verification.

---

## ⚡ 2-Step Setup for Antigravity (AGY)

### Step 1: Register the MCP Server
Find your `uv` path by running `which uv` in your terminal (e.g. `/home/user/.local/bin/uv`).

Add to `~/.gemini/config/mcp_config.json`:
```json
{
  "mcpServers": {
    "debug-harness": {
      "command": "/path/to/your/uv",
      "args": ["run", "--directory", "/path/to/debug-harness", "harness", "mcp"]
    }
  }
}
```

### Step 2: Enable the `/harness` Slash Command
Copy [`skills/harness/SKILL.md`](skills/harness/SKILL.md) to your Antigravity skills directory:
```bash
mkdir -p ~/.gemini/config/skills/harness
cp skills/harness/SKILL.md ~/.gemini/config/skills/harness/SKILL.md
```

Restart or reload your agent window (`Ctrl+Shift+P` -> *Developer: Reload Window*).

---

## 💬 How to Use in Chat

Once installed, use the `/harness` slash command directly in chat:

```text
/harness The analytics dashboard is showing wildly inflated revenue and order numbers.
```

### What happens automatically:
1. **Zero Guessing**: The `/harness` command instructs the agent to invoke the `harness_step` tool directly (no bash file searches).
2. **Deterministic Traversal**: The agent receives only **1 function at a time** with its exact AST code and 1-hop callers/callees.
3. **Sandbox Gate**: When all links finish, changes are verified in an in-memory test sandbox before touching disk.

---

## 💻 Terminal CLI Usage (Optional)

If you prefer running from the command line:

```bash
# View symbol outline to find function/route names:
harness outline --repo ./my_project

# Step through a bug with terminal logs:
harness step --repo ./my_project --symptom compute_total --logs

# Handle multiple glitches at once:
harness step --repo ./my_project --symptoms checkout_route --symptoms cart_total --logs run_log.txt

# View past session traversal logs:
harness logs <session_id>
```
