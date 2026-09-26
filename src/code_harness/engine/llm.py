"""Lightweight LLM caller supporting Gemini, OpenAI, and OpenAI-compatible endpoints.

Uses Python standard library (urllib.request) to avoid bulky external SDK dependencies.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, Optional


class LLMClient:
    """Unified client for live LLM patch generation."""

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.gemini_key = api_key or os.getenv("GEMINI_API_KEY")
        self.openai_key = api_key or os.getenv("OPENAI_API_KEY")
        self.base_url = base_url or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        
        # Default model selection based on available keys
        if model:
            self.model = model
        elif self.gemini_key:
            self.model = "gemini-1.5-flash"
        else:
            self.model = "gpt-4o-mini"

    def complete(self, system_prompt: str, user_prompt: str) -> str:
        """Call LLM API and return synthesized text."""
        # 1. Prefer Gemini API if key is present or model is gemini
        if self.gemini_key and "gemini" in self.model.lower():
            return self._call_gemini(system_prompt, user_prompt)

        # 2. Call OpenAI / OpenAI-compatible endpoint
        if self.openai_key or "localhost" in self.base_url or "127.0.0.1" in self.base_url:
            return self._call_openai(system_prompt, user_prompt)

        raise ValueError(
            "No API key found. Please set GEMINI_API_KEY or OPENAI_API_KEY environment variable, "
            "or provide --api-key / pass to Harness(api_key=...)."
        )

    def _call_gemini(self, system_prompt: str, user_prompt: str) -> str:
        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:generateContent"
            f"?key={self.gemini_key}"
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

    def _call_openai(self, system_prompt: str, user_prompt: str) -> str:
        endpoint = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
        }
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.openai_key or 'dummy'}",
        }
        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                choices = result.get("choices", [])
                if choices:
                    return choices[0].get("message", {}).get("content", "")
                return ""
        except urllib.error.HTTPError as e:
            err_msg = e.read().decode("utf-8")
            raise RuntimeError(f"OpenAI API Error ({e.code}): {err_msg}")
