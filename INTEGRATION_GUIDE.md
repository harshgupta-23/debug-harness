# Agent Integration & GitHub Installation Guide

Integrate the **Deterministic Code-Graph Harness** directly into **Antigravity (AGY)**, **Claude Code**, **Cursor**, **Aider**, or any custom agent workflow straight from GitHub.

---

## 1. Direct Installation from GitHub

No local cloning required. Install or execute directly using `uv` or `pip`:

```bash
# Option A: Run ephemerally via uvx (zero-install)
uvx --from git+https://github.com/<your-username>/debug-harness.git harness --help

# Option B: Global CLI installation via uv tool
uv tool install git+https://github.com/<your-username>/debug-harness.git

# Option C: Standard pip install into existing environment
pip install git+https://github.com/<your-username>/debug-harness.git
```

---

## 2. Agent Integration Options

### A. Antigravity (AGY) Integration

Add the harness as an MCP tool to your AGY configuration (e.g., `~/.gemini/antigravity/mcp.json` or workspace settings):

```json
{
  "mcpServers": {
    "code-harness": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/<your-username>/debug-harness.git", "harness", "mcp"],
      "env": {
        "GEMINI_API_KEY": "${GEMINI_API_KEY}",
        "OPENAI_API_KEY": "${OPENAI_API_KEY}"
      }
    }
  }
}
```

Now AGY can autonomously invoke:
- `harness_fix(repo_path, issue, apply=True, use_harness=True)`
- `harness_blast_radius(repo_path, node_id)`

---

### B. Claude Code Integration

Register the harness with Claude Code CLI:

```bash
claude mcp add code-harness uvx --from git+https://github.com/<your-username>/debug-harness.git harness mcp
```

Or in Claude Desktop (`~/.config/Claude/claude_desktop_config.json`):

```json
{
  "mcpServers": {
    "code-harness": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/<your-username>/debug-harness.git", "harness", "mcp"]
    }
  }
}
```

---

### C. Cursor & OpenHands Integration

In Cursor Settings → Features → MCP:
- **Type**: `command`
- **Command**: `uvx --from git+https://github.com/<your-username>/debug-harness.git harness mcp`

---

### D. Direct Python SDK in Custom Agents

If your agent is written in Python (LangChain, LlamaIndex, AutoGen, custom loop):

```python
from code_harness import Harness

# Initialize targeting a workspace
harness = Harness(
    repo_path="/path/to/target/project",
    use_harness=True,                         # Toggle ON: deterministic parser + sandbox
    model="gemini-1.5-flash",                 # Or gpt-4o, claude-3-5-sonnet, local
)

# Run bugfix pipeline
result = harness.fix(
    issue="Order total calculation throws NoneType discount_rate error",
    apply=True,  # Commit verified diffs directly to files
)

if result.success:
    print(f"Verified & applied! Plan ID: {result.plan_id}")
    print(f"Files touched: {result.touched_files}")
else:
    print(f"Fix failed sandbox gate: {result.diagnostics}")
```

---

## 3. Configuring Models & API Providers

Developers use different models for different tasks (e.g., cheap fast models for triage, frontier models for complex architectural mutations, or local self-hosted models for privacy).

### Supported Provider Environment Variables

| Provider / Target | Environment Variable | Default Model Example |
|---|---|---|
| **Google Gemini** | `export GEMINI_API_KEY="AIza..."` | `gemini-1.5-flash`, `gemini-1.5-pro` |
| **OpenAI** | `export OPENAI_API_KEY="sk-..."` | `gpt-4o-mini`, `gpt-4o` |
| **Anthropic / OpenRouter** | `export OPENAI_BASE_URL="https://openrouter.ai/api/v1"`<br>`export OPENAI_API_KEY="sk-or-..."` | `anthropic/claude-3.5-sonnet` |
| **Local (Ollama / vLLM)** | `export OPENAI_BASE_URL="http://localhost:11434/v1"`<br>`export OPENAI_API_KEY="ollama"` | `qwen2.5-coder:7b`, `deepseek-coder` |

### Multi-Model Usage Strategies

#### 1. Fast Routine Bugfixes (Cost/Latency Efficient)
```bash
harness fix --repo ./my_app --issue "Fix regex phone parser" --model "gemini-1.5-flash" --apply
```

#### 2. Deep Cross-Boundary Refactors (High Reasoning)
```bash
harness fix --repo ./my_app --issue "Migrate discount schema from float to object" --model "gpt-4o" --apply
```

#### 3. Air-Gapped / Local Inference (Zero Data Leakage)
Start Ollama or vLLM locally, then:
```bash
export OPENAI_BASE_URL="http://localhost:11434/v1"
harness fix --repo ./my_app --issue "Fix indexing bug" --model "qwen2.5-coder:7b" --apply
```

---

## 4. The Toggle: When to Use What

| Parameter | `--harness` (Default) | `--no-harness` |
|---|---|---|
| **Graph Indexing** | Deterministic AST + cross-boundary linking | Skipped |
| **Context Window** | Minimal scoped slices (< 2,000 tokens) | Raw whole files |
| **Atomic Contract** | Locks DB + API + Frontend | Single file prompt |
| **Sandbox Gate** | AST syntax check + targeted tests | Unverified |
| **Best Used For** | Production codebases, multi-layer bugs | Quick raw prompt generation |
