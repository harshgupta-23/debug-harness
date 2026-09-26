---
name: debug
description: Deterministic code-graph debugging harness. Steps through bugs 1 node at a time with sandbox verification. Trigger with /debug.
---

# Deterministic Debug Harness Workflow

Triggered when the user invokes `/debug <bug description>` or asks to debug with the harness.

## Rules of Engagement
1. **NEVER search the filesystem for binaries** (DO NOT run `which debug-harness` or `find`).
2. The harness is an **MCP tool**, not a shell binary.
3. If you need to locate starting function or route symbols, call `harness_outline(repo_path=".")`.
4. Call `harness_step(repo_path=".", issue="...", symptoms=[...])`:
   - Focuses strictly on `curr` (symbol, file, lines, AST code) and its depth-1 neighbors.
   - You are **STRICTLY RESTRICTED** to provide `curr_patch` for `curr` ONLY.
   - Set `modify_next_nodes` to the neighbor node IDs that must be modified next.
   - Continue stepping until all links finish and verification passes.
