"""Recorded Groq calls for research only. No dependency on historical pools."""

import fcntl
import hashlib
import json
import os
import re
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE = "https://api.groq.com/openai/v1"
QWEN = "qwen/qwen3.8-27b"
OSS = "openai/gpt-oss-20b"


class Groq:
    def __init__(self, output: Path, env: Path | None, interval: float = 3) -> None:
        if env:
            load_dotenv(env)
        self.headers = {"Authorization": f"Bearer {os.environ['GROQ_API_KEY']}"}
        self.output = output
        self.interval = interval
        run_id = hashlib.sha256(str(output.resolve()).encode()).hexdigest()[:16]
        self.state = Path("results/research-transport") / run_id
        self.state.mkdir(parents=True, exist_ok=True)

    def preflight(self, models: set[str]) -> None:
        response = requests.get(f"{BASE}/models", headers=self.headers, timeout=30)
        if not response.ok:
            raise RuntimeError(f"Groq preflight HTTP {response.status_code}")
        available = {row["id"] for row in response.json()["data"]}
        if not models <= available:
            raise RuntimeError(f"Groq models unavailable: {sorted(models - available)}")

    def call(
        self, slot: str, model: str, prompt: str, temperature: float,
        history: tuple[dict[str, str], ...] = (),
    ) -> dict:
        path = self.output / f"{slot}.json"
        body = {
            "model": model,
            "messages": [*history, {"role": "user", "content": prompt}],
            "temperature": temperature,
            "top_p": 1,
            "max_completion_tokens": 768,
            "reasoning_effort": "none" if model == QWEN else "low",
            "response_format": {"type": "json_object"},
        }
        model_name = model.replace("/", "-")
        with (self.state / f"{model_name}.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            return self._call_locked(path, body, model_name)

    def _call_locked(self, path: Path, body: dict, model_name: str) -> dict:
        if path.exists():
            saved = json.loads(path.read_text())
            if saved["request"] != body:
                raise ValueError(f"Stored request differs: {path.stem}")
            return saved["response"]

        pace_path = self.state / f"{model_name}.json"
        attempt_path = self.state / path.name
        next_post = float(pace_path.read_text()) if pace_path.exists() else 0.0
        attempts = json.loads(attempt_path.read_text()) if attempt_path.exists() else []
        for retry in range(4):
            time.sleep(max(0.0, next_post - time.time()))
            start = time.time()
            print(f"{path.stem} → {body['model']}", flush=True)
            response = requests.post(
                f"{BASE}/chat/completions", headers=self.headers, json=body,
                timeout=60, allow_redirects=False,
            )
            limit_headers = {
                key: response.headers[key] for key in (
                    "Retry-After", "X-RateLimit-Remaining-Tokens", "X-RateLimit-Reset-Tokens",
                ) if key in response.headers
            }
            attempts.append({
                "status": response.status_code, "seconds": round(time.time() - start, 3),
                "rate": limit_headers,
            })
            spacing = max(self.interval, 7 if body["model"] == QWEN else 3)
            next_post = start + spacing
            remaining = response.headers.get("x-ratelimit-remaining-tokens", "")
            reset = _duration(response.headers.get("x-ratelimit-reset-tokens", ""))
            if remaining.isdigit() and int(remaining) < 1600:
                next_post = max(next_post, time.time() + reset + 2)
            if response.status_code == 429:
                _write(attempt_path, attempts)
                delay = response.headers.get("Retry-After", "")
                wait = float(delay) if delay.isdigit() else 0
                next_post = max(next_post, time.time() + max(wait, reset, 1) + 2)
                pace_path.write_text(str(next_post))
                if not 0 < wait <= 60:
                    raise RuntimeError(f"Groq quota HTTP 429 at {path.stem}, retry-after={delay}")
                if retry < 3:
                    continue
                raise RuntimeError(f"Groq quota HTTP 429 after retries at {path.stem}")
            pace_path.write_text(str(next_post))
            if response.status_code not in (200, 400):
                _write(attempt_path, attempts)
                raise RuntimeError(f"Groq HTTP {response.status_code} at {path.stem}")
            data = response.json()
            if response.status_code == 400:
                # Provider diagnostics can contain account identifiers.
                code = data.get("error", {}).get("code")
                if code != "json_validate_failed":
                    raise RuntimeError(f"Groq configuration HTTP 400 at {path.stem}, code={code}")
                data = {"error": code}
            _write(path, {"request": body, "response": data, "posts": attempts})
            attempt_path.unlink(missing_ok=True)
            return data
        raise AssertionError("Retry loop exhausted")


def _duration(value: str) -> float:
    match = re.fullmatch(r"(?:(\d+)m)?(\d+(?:\.\d+)?)s", value)
    return (60 * int(match[1] or 0) + float(match[2])) if match else 0.0


def _write(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value) + "\n")
    temporary.replace(path)


def content(response: dict) -> str:
    try:
        value = response["choices"][0]["message"]["content"]
        return value if isinstance(value, str) else ""
    except (KeyError, IndexError, TypeError):
        return ""


def payload(response: dict) -> dict:
    try:
        value = json.loads(content(response))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}
