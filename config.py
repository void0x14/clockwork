"""YAML config loader with deep-merge and dot-access helpers."""

import yaml
from pathlib import Path
from typing import Any

_DEFAULTS: dict = {
    "youtube": {
        "channel_url": "",
        "client_secrets_file": "client_secrets.json",
        "token_file": "token.json",
    },
    "subtitle": {
        "languages": ["tr", "tr-orig", "en", "en-orig"],
        "output_dir": "./subtitles",
        "prefer_manual": True,
    },
    "ai": {
        "default_provider": "anthropic",
        "providers": {
            "anthropic":       {"api_key": "", "model": "claude-sonnet-4-20250514"},
            "openai":          {"api_key": "", "model": "gpt-4o"},
            "gemini":          {"api_key": "", "model": "gemini-3.5-flash",
                                "thinking_level": "HIGH", "include_thoughts": False},
            "groq":            {"api_key": "", "model": "llama-3.3-70b-versatile",
                                "base_url": "https://api.groq.com/openai/v1"},
            "together":        {"api_key": "", "model": "",
                                "base_url": "https://api.together.xyz/v1"},
            "ollama":          {"base_url": "http://localhost:11434", "model": "llama3.2:latest"},
            "lmstudio":        {"base_url": "http://localhost:1234/v1", "api_key": "lm-studio", "model": ""},
            "openai_compatible": {"base_url": "", "api_key": "", "model": ""},
        },
    },
    "processing": {
        "skip_with_chapters": True,
        "save_srt": True,
        "save_timestamps": True,
        "timestamps_dir": "./timestamps",
        "state_file": "./state.json",
        "delay_between_videos": 1.5,
        "max_retries": 3,
        "dry_run": False,
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    result = dict(base)
    for k, v in override.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = _deep_merge(result[k], v)
        else:
            result[k] = v
    return result


class Config:
    def __init__(self, path: str = "config.yaml"):
        self._data = _DEFAULTS
        p = Path(path)
        if p.exists():
            with p.open(encoding="utf-8") as f:
                loaded = yaml.safe_load(f) or {}
            self._data = _deep_merge(_DEFAULTS, loaded)

    def get(self, *keys: str, default: Any = None) -> Any:
        node = self._data
        for k in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(k)
            if node is None:
                return default
        return node

    def __getitem__(self, key: str) -> Any:
        return self._data[key]
