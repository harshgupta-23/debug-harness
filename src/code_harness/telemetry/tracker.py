"""Telemetry, metrics collection, and side-by-side benchmark comparison.

Strictly enforces:
- Tracks wall-clock latency, total LLM API invocations, and precise token metrics
  (input tokens, output tokens, total tokens).
- No pricing or monetary calculations.
- Generates side-by-side comparison tables and exports clean JSON/Markdown reports.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ExecutionMetrics(BaseModel):
    mode_name: str
    llm_api_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    wall_clock_seconds: float = 0.0
    atomic_dependents_locked: int = 0
    total_atomic_dependents: int = 0
    dependents_detail: str = ""
    verification_status: str = "UNKNOWN"
    notes: List[str] = Field(default_factory=list)


class BenchmarkComparison(BaseModel):
    issue_name: str
    repository: str
    model_name: str
    baseline: ExecutionMetrics
    harness: ExecutionMetrics
    timestamp: float = Field(default_factory=time.time)

    def context_reduction_percentage(self) -> float:
        if self.baseline.total_tokens == 0:
            return 0.0
        reduction = (1 - (self.harness.total_tokens / self.baseline.total_tokens)) * 100
        return max(0.0, round(reduction, 1))

    def speedup_factor(self) -> float:
        if self.harness.wall_clock_seconds == 0:
            return 1.0
        speedup = self.baseline.wall_clock_seconds / self.harness.wall_clock_seconds
        return max(1.0, round(speedup, 1))

    def format_terminal_table(self) -> str:
        """Render standard showcase comparison table."""
        reduction_pct = self.context_reduction_percentage()
        speedup = self.speedup_factor()

        base = self.baseline
        harn = self.harness

        lines = [
            "========================= BENCHMARK SUMMARY =========================",
            f"{'Metric':<25} {'Baseline (Standard Agent)':<27} {'Harness Mode'}",
            "---------------------------------------------------------------------",
            f"{'Total LLM API Calls':<25} {f'{base.llm_api_calls} calls':<27} {f'{harn.llm_api_calls} call' if harn.llm_api_calls == 1 else f'{harn.llm_api_calls} calls'}",
            f"{'Input Tokens Consumed':<25} {f'{base.input_tokens:,} tokens':<27} {f'{harn.input_tokens:,} tokens'}",
            f"{'Output Tokens Generated':<25} {f'{base.output_tokens:,} tokens':<27} {f'{harn.output_tokens:,} tokens'}",
            f"{'Total Context Size':<25} {f'{base.total_tokens:,} tokens':<27} {f'{harn.total_tokens:,} tokens ({reduction_pct}% reduction)'}",
            f"{'Total Execution Time':<25} {f'{base.wall_clock_seconds:.1f}s':<27} {f'{harn.wall_clock_seconds:.1f}s ({speedup}x speedup)'}",
            f"{'Atomic Dependents Locked':<25} {f'{base.atomic_dependents_locked} / {base.total_atomic_dependents} {base.dependents_detail}':<27} {f'{harn.atomic_dependents_locked} / {harn.total_atomic_dependents} {harn.dependents_detail}'}",
            f"{'Verification Status':<25} {base.verification_status:<27} {harn.verification_status}",
            "=====================================================================",
        ]
        return "\n".join(lines)

    def to_markdown(self) -> str:
        reduction_pct = self.context_reduction_percentage()
        speedup = self.speedup_factor()
        base = self.baseline
        harn = self.harness

        return f"""# Benchmark Comparison: {self.issue_name}

- **Repository**: `{self.repository}`
- **Model**: `{self.model_name}`
- **Context Reduction**: **{reduction_pct}%**
- **Speedup**: **{speedup}x**

| Metric | Baseline (Standard Agent) | Harness Mode |
|---|---|---|
| **Total LLM API Calls** | {base.llm_api_calls} calls | {harn.llm_api_calls} calls |
| **Input Tokens Consumed** | {base.input_tokens:,} | {harn.input_tokens:,} |
| **Output Tokens Generated** | {base.output_tokens:,} | {harn.output_tokens:,} |
| **Total Context Size** | {base.total_tokens:,} tokens | {harn.total_tokens:,} tokens ({reduction_pct}% reduction) |
| **Total Execution Time** | {base.wall_clock_seconds:.2f}s | {harn.wall_clock_seconds:.2f}s ({speedup}x speedup) |
| **Atomic Dependents Locked** | {base.atomic_dependents_locked} / {base.total_atomic_dependents} ({base.dependents_detail}) | {harn.atomic_dependents_locked} / {harn.total_atomic_dependents} ({harn.dependents_detail}) |
| **Verification Status** | `{base.verification_status}` | `{harn.verification_status}` |
"""

    def export_summary(self, output_dir: Path) -> Tuple[Path, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        json_path = output_dir / f"benchmark_{self.issue_name.replace(' ', '_').lower()}.json"
        md_path = output_dir / f"benchmark_{self.issue_name.replace(' ', '_').lower()}.md"

        json_path.write_text(self.model_dump_json(indent=2), encoding="utf-8")
        md_path.write_text(self.to_markdown(), encoding="utf-8")
        return json_path, md_path


class TelemetryTracker:
    """Session telemetry tracker recording metrics during runs."""

    def __init__(self, mode_name: str) -> None:
        self.mode_name = mode_name
        self.metrics = ExecutionMetrics(mode_name=mode_name)
        self._start_time = time.perf_counter()

    def record_llm_call(self, input_tokens: int, output_tokens: int) -> None:
        self.metrics.llm_api_calls += 1
        self.metrics.input_tokens += input_tokens
        self.metrics.output_tokens += output_tokens
        self.metrics.total_tokens += (input_tokens + output_tokens)

    def record_dependents(self, locked: int, total: int, detail: str = "") -> None:
        self.metrics.atomic_dependents_locked = locked
        self.metrics.total_atomic_dependents = total
        self.metrics.dependents_detail = detail

    def record_verification(self, status: str) -> None:
        self.metrics.verification_status = status

    def stop(self) -> ExecutionMetrics:
        self.metrics.wall_clock_seconds = round(time.perf_counter() - self._start_time, 2)
        return self.metrics
