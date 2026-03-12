"""
Native Ollama chat wrapper for the benchmark lane.
"""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request


LOCAL_MODEL = "qwen3.5"
LOCAL_BASE_URL = "http://localhost:11434"
MAX_RETRIES = 3
REPETITION_PENALTY = 1.15


def get_ollama_client():
    """Compatibility shim for benchmark modules that expect a client object."""
    return None


def call_local(
    _client,
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    model: str = LOCAL_MODEL,
    format_json: bool = False,
) -> tuple[str, int, dict]:
    messages = []
    if system_prompt.strip():
        messages.append({"role": "system", "content": system_prompt})
    messages.append({"role": "user", "content": user_prompt})

    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "think": False,
        "options": {
            "temperature": temperature,
            "num_predict": max_tokens,
            "repeat_penalty": REPETITION_PENALTY,
        },
    }
    if format_json:
        payload["format"] = "json"

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            data = _post_chat(payload)
            text = (
                data.get("message", {}).get("content")
                or data.get("response")
                or ""
            )
            text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
            tokens = int(data.get("prompt_eval_count", 0) or 0) + int(data.get("eval_count", 0) or 0)
            if text:
                return text, tokens, data

            last_error = ValueError(
                "Empty content returned by Ollama chat response"
            )
        except Exception as exc:  # pragma: no cover - retry path
            last_error = exc

        if attempt < MAX_RETRIES - 1:
            time.sleep(3)

    raise last_error if last_error else RuntimeError("Ollama chat request failed")


def _post_chat(payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{LOCAL_BASE_URL}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read().decode("utf-8"))
