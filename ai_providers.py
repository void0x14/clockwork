"""AI provider abstraction layer.

Supported providers
-------------------
- anthropic       Claude API (native)
- openai          OpenAI API (native)
- gemini          Google Gemini (native)
- groq            Groq (OpenAI-compatible)
- together        Together AI (OpenAI-compatible)
- ollama          Ollama local server (native /api/generate)
- lmstudio        LM Studio (OpenAI-compatible)
- openai_compatible  Any OpenAI-compatible endpoint
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Dict

# ---------------------------------------------------------------------- prompt

_SYSTEM_PROMPT = (
    "You are a YouTube chapter timestamp generator. "
    "Output ONLY timestamps — no explanations, no preamble, no markdown."
)

_USER_TEMPLATE = """\
Video Title: {title}
Video Duration: {duration}

Transcript (each line begins with [MM:SS] indicating when that segment starts):
{transcript}

Generate chapter timestamps for this video.

Rules:
- Output timestamps ONLY — nothing else
- Format: MM:SS Chapter Title   (use HH:MM:SS only if the video is over 1 hour)
- First timestamp MUST be 00:00
- 5–15 chapters proportional to video length
- Titles ≤ 50 characters, in the SAME language as the transcript
- Mark real topic changes, not arbitrary time cuts
- Base times on the [MM:SS] markers in the transcript"""


def _build_prompt(title: str, transcript: str, duration: str = "") -> str:
    return _USER_TEMPLATE.format(
        title=title,
        duration=duration or "unknown",
        transcript=transcript,
    )


# ------------------------------------------------------------------ base class

class AIProvider(ABC):
    @abstractmethod
    def generate(self, title: str, transcript: str, duration: str = "") -> str:
        """Call the AI and return raw text (may contain timestamps + other text)."""


# --------------------------------------------------------------- Anthropic ----

class AnthropicProvider(AIProvider):
    def __init__(self, cfg: Dict):
        try:
            import anthropic
        except ImportError:
            raise ImportError("pip install anthropic")
        self._client = anthropic.Anthropic(api_key=cfg["api_key"])
        self._model  = cfg.get("model", "claude-sonnet-4-20250514")

    def generate(self, title: str, transcript: str, duration: str = "") -> str:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": _build_prompt(title, transcript, duration)}],
        )
        return resp.content[0].text


# --------------------------------------------------------------- OpenAI ------

class _OpenAICompatProvider(AIProvider):
    """Shared logic for OpenAI, Groq, Together, LM Studio, any compat endpoint."""

    def __init__(self, api_key: str, model: str, base_url: str | None = None):
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError("pip install openai")
        kwargs: Dict = {"api_key": api_key or "dummy"}
        if base_url:
            kwargs["base_url"] = base_url
        self._client = OpenAI(**kwargs)
        self._model  = model

    def generate(self, title: str, transcript: str, duration: str = "") -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            max_tokens=1024,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user",   "content": _build_prompt(title, transcript, duration)},
            ],
        )
        return resp.choices[0].message.content


class OpenAIProvider(_OpenAICompatProvider):
    def __init__(self, cfg: Dict):
        super().__init__(cfg["api_key"], cfg.get("model", "gpt-4o"))


class GroqProvider(_OpenAICompatProvider):
    def __init__(self, cfg: Dict):
        super().__init__(
            cfg["api_key"],
            cfg.get("model", "llama-3.3-70b-versatile"),
            base_url=cfg.get("base_url", "https://api.groq.com/openai/v1"),
        )


class TogetherProvider(_OpenAICompatProvider):
    def __init__(self, cfg: Dict):
        super().__init__(
            cfg["api_key"],
            cfg.get("model", "meta-llama/Llama-3.3-70B-Instruct-Turbo"),
            base_url=cfg.get("base_url", "https://api.together.xyz/v1"),
        )


class LMStudioProvider(_OpenAICompatProvider):
    def __init__(self, cfg: Dict):
        super().__init__(
            cfg.get("api_key", "lm-studio"),
            cfg.get("model") or "default",  # LM Studio ignores model name
            base_url=cfg.get("base_url", "http://localhost:1234/v1"),
        )


class OpenAICompatProvider(_OpenAICompatProvider):
    def __init__(self, cfg: Dict):
        super().__init__(cfg["api_key"], cfg["model"], base_url=cfg.get("base_url"))


# --------------------------------------------------------------- Gemini ------

class GeminiProvider(AIProvider):
    def __init__(self, cfg: Dict):
        try:
            import google.generativeai as genai
        except ImportError:
            raise ImportError("pip install google-generativeai")
        genai.configure(api_key=cfg["api_key"])
        self._model = genai.GenerativeModel(
            model_name=cfg.get("model", "gemini-1.5-pro"),
            system_instruction=_SYSTEM_PROMPT,
        )

    def generate(self, title: str, transcript: str, duration: str = "") -> str:
        resp = self._model.generate_content(_build_prompt(title, transcript, duration))
        return resp.text


# --------------------------------------------------------------- Ollama ------

class OllamaProvider(AIProvider):
    def __init__(self, cfg: Dict):
        try:
            import httpx
            self._httpx = httpx
        except ImportError:
            raise ImportError("pip install httpx")
        self._base = cfg.get("base_url", "http://localhost:11434").rstrip("/")
        self._model = cfg.get("model", "llama3.2:latest")

    def generate(self, title: str, transcript: str, duration: str = "") -> str:
        payload = {
            "model":  self._model,
            "prompt": f"{_SYSTEM_PROMPT}\n\n{_build_prompt(title, transcript, duration)}",
            "stream": False,
            "options": {"num_predict": 1024},
        }
        resp = self._httpx.post(
            f"{self._base}/api/generate", json=payload, timeout=180.0
        )
        resp.raise_for_status()
        return resp.json()["response"]


# --------------------------------------------------------------- factory ------

_REGISTRY = {
    "anthropic":        AnthropicProvider,
    "openai":           OpenAIProvider,
    "gemini":           GeminiProvider,
    "groq":             GroqProvider,
    "together":         TogetherProvider,
    "ollama":           OllamaProvider,
    "lmstudio":         LMStudioProvider,
    "openai_compatible": OpenAICompatProvider,
}


def get_provider(name: str, ai_cfg: Dict) -> AIProvider:
    cls = _REGISTRY.get(name)
    if cls is None:
        available = ", ".join(_REGISTRY)
        raise ValueError(f"Unknown provider '{name}'. Available: {available}")
    provider_cfg = ai_cfg.get("providers", {}).get(name, {})
    return cls(provider_cfg)
