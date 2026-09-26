"""Single-model LLM client for Antigravity (AGY) using Gemini.

Uses Python standard library (urllib.request) without heavy dependencies.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional


class LLMClient:
    """Lightweight caller for Gemini (standard AGY model runtime)."""

    def __init__(
        self,
        model: str = "gemini-1.5-flash",
        api_key: Optional[str] = None,
    ) -> None:
        self.model = model or "gemini-1.5-flash"
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Call Gemini API and return synthesized text."""
        if not self.api_key:
            raise ValueError(
                "GEMINI_API_KEY is not set. Export it in your environment or set it in your AGY MCP config."
            )

        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            f"?key={self.api_key}"
        )
        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": f"{system_prompt}\n\nUser Request:\n{user_prompt}"}],
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 4096,
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                candidates = result.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts:
                        return parts[0].get("text", "")
                return ""
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8")
            raise RuntimeError(f"Gemini API Error ({e.code}): {err_msg}")
