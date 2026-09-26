# Antigravity (AGY) Integration Guide

Connect the **Deterministic Code-Graph Harness** to **Antigravity (AGY)** using the `/harness` slash command and MCP tool integration.

---

## 🛠️ Setup Guide (2 Steps)

### Step 1: Add to Global MCP Configuration
1. In your terminal, check the absolute path to `uv`:
   ```bash
   which uv
   # Example output: /home/hp/.local/bin/uv
   ```

2. Add this configuration to [`~/.gemini/config/mcp_config.json`](file:///home/hp/.gemini/config/mcp_config.json):
   ```json
   {
     "mcpServers": {
       "debug-harness": {
         "command": "/home/hp/.local/bin/uv",
         "args": [
           "run",
           "--directory",
           "/home/hp/projects/debug-harness",
           "harness",
           "mcp"
         ]
       }
     }
   }
   ```
   *(Note: Using the full path to `uv` prevents PATH resolution errors in desktop GUI sessions).*

### Step 2: Enable the `/harness` Slash Command
Copy the bundled skill into your Antigravity skills directory:
```bash
mkdir -p ~/.gemini/config/skills/harness
cp skills/harness/SKILL.md ~/.gemini/config/skills/harness/SKILL.md
```

Reload your window (`Ctrl+Shift+P` -> *Developer: Reload Window*).

---

## 🚀 How to Use in Chat

Type `/harness` followed by the problem description:

```text
/harness The analytics dashboard is showing wildly inflated revenue and order numbers.
```

### Protocol Workflow
1. **Symbol Mapping**: The agent calls `harness_outline` or directly passes the symptoms to `harness_step`.
2. **Shared Root or Disjoint Queue**:
   - If symptoms share a common dependency, the harness collapses them to the shared root function.
   - If independent, the harness queues them sequentially.
3. **Strict 1-Node Boundary**: The agent receives ONLY the current focused function (`curr`) and its 1-hop upstream/downstream neighbors. It outputs a patch for `curr` and marks any neighbor to modify next.
4. **Sandbox Gate**: Once all links return empty, the harness executes tests in an in-memory AST sandbox and commits the verified patch to disk.

---

## 🔍 Verifying the MCP Server

Test that your MCP server responds over stdio:
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | uv run --directory /home/hp/projects/debug-harness harness mcp
```
You will see JSON listing `harness_step`, `harness_outline`, and `harness_blast_radius`.
