import json
import os
import time
from dataclasses import dataclass
from typing import Protocol

import requests

from dualify.cloud_providers import profile_for_base_url


class LLMClient(Protocol):
    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict: ...

    def healthcheck(self) -> None: ...


def _extract_json_object(raw_text: str) -> dict:
    try:
        parsed = json.loads(raw_text)
    except json.JSONDecodeError:
        parsed = None
    if isinstance(parsed, dict):
        return parsed

    start = raw_text.find("{")
    end = raw_text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise json.JSONDecodeError("No JSON object found in model response", raw_text, 0)
    return json.loads(raw_text[start : end + 1])


@dataclass
class OllamaClient:
    model: str
    base_url: str = "http://127.0.0.1:11434"
    timeout_sec: int = 30

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature},
        }
        response = requests.post(url, json=payload, timeout=self.timeout_sec)
        response.raise_for_status()
        body = response.json()
        raw_text = body.get("response", "{}")
        return json.loads(raw_text)

    def healthcheck(self) -> None:
        url = f"{self.base_url}/api/version"
        response = requests.get(url, timeout=10)
        response.raise_for_status()


@dataclass
class OpenAICompatibleClient:
    model: str
    base_url: str
    api_key: str = ""
    timeout_sec: int = 60
    max_retries: int = 6
    backoff_base_sec: float = 2.0
    max_backoff_sec: float = 60.0
    fixed_chat_mode: bool | None = None

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _debug_raw(self, label: str, raw_text: str) -> None:
        if os.environ.get("DUALIFY_DEBUG_LLM_RAW", "0") != "1":
            return
        snippet = raw_text[:500].replace("\n", "\\n")
        print(f"[dualify-debug] {label}: {snippet}")

    def _extract_choice_text(self, choice: dict, *, chat_mode: bool) -> str:
        if not isinstance(choice, dict):
            raise ValueError("Completion response choice has invalid shape")
        if chat_mode:
            message = choice.get("message", {})
            if not isinstance(message, dict):
                raise ValueError("Chat completion choice message has invalid shape")
            content = message.get("content", "")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                text_parts: list[str] = []
                for part in content:
                    if isinstance(part, dict):
                        text = part.get("text", "")
                        if isinstance(text, str):
                            text_parts.append(text)
                return "\n".join(text_parts)
            raise ValueError("Chat completion content has invalid shape")
        text = choice.get("text", "")
        if not isinstance(text, str):
            raise ValueError("Completion response text is not a string")
        return text

    def _post_with_retry(self, url: str, payload: dict) -> requests.Response:
        """POST with exponential backoff on rate limits / transient server errors.

        Cloud OpenAI-compatible providers (Groq, SambaNova) rate-limit with HTTP
        429 and occasionally return 5xx. Without backoff these surface as
        exceptions that the extraction phases swallow into degraded ``ret == ret``
        outputs, silently corrupting cross-model results. Retrying honors any
        ``Retry-After`` header and otherwise backs off exponentially.
        """
        last_exc: Exception | None = None
        last_response: requests.Response | None = None
        for attempt in range(self.max_retries):
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=self._headers(),
                    timeout=self.timeout_sec,
                )
            except requests.RequestException as exc:
                last_exc = exc
                delay = min(self.backoff_base_sec * (2**attempt), self.max_backoff_sec)
                print(
                    f"[dualify-llm] request error (attempt {attempt + 1}/{self.max_retries}): "
                    f"{exc}; sleeping {delay:.1f}s",
                    flush=True,
                )
                time.sleep(delay)
                continue
            last_response = response
            if response.status_code in (429, 500, 502, 503, 504):
                retry_after = response.headers.get("Retry-After")
                default_delay = self.backoff_base_sec * (2**attempt)
                try:
                    delay = float(retry_after) if retry_after else default_delay
                except ValueError:
                    delay = default_delay
                delay = min(max(delay, self.backoff_base_sec), self.max_backoff_sec)
                print(
                    f"[dualify-llm] HTTP {response.status_code} (attempt {attempt + 1}/"
                    f"{self.max_retries}); sleeping {delay:.1f}s",
                    flush=True,
                )
                time.sleep(delay)
                continue
            return response
        if last_exc is not None:
            raise last_exc
        if last_response is not None:
            return last_response
        raise RuntimeError("POST failed with no response")

    def _prefers_chat_mode(self) -> bool:
        """Local vLLM/Ollama gateways usually support chat+json; Groq/SambaNova often do not."""
        override = os.environ.get("DUALIFY_OPENAI_USE_CHAT")
        if override is not None:
            return override == "1"
        host = self.base_url.lower()
        return not (
            "groq.com" in host or "sambanova.ai" in host or "openrouter.ai" in host
        )

    def generate_json(self, prompt: str, temperature: float = 0.0) -> dict:
        # Для RQ1 режим фиксируют заранее: ошибка формата должна попасть в native repair.
        if self.fixed_chat_mode is not None:
            attempts = [self.fixed_chat_mode]
        else:
            prefer_chat = self._prefers_chat_mode()
            attempts = [True, False] if prefer_chat else [False, True]
        last_exc: Exception | None = None

        for chat_mode in attempts:
            endpoint = "/v1/chat/completions" if chat_mode else "/v1/completions"
            url = f"{self.base_url}{endpoint}"
            if chat_mode:
                payload = {
                    "model": self.model,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Return only a strict JSON object.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    "max_tokens": 1024,
                    "temperature": temperature,
                    "response_format": {"type": "json_object"},
                }
            else:
                payload = {
                    "model": self.model,
                    "prompt": prompt,
                    "max_tokens": 1024,
                    "temperature": temperature,
                }
            try:
                response = self._post_with_retry(url, payload)
                response.raise_for_status()
                body = response.json()
                choices = body.get("choices", [])
                if not isinstance(choices, list) or not choices:
                    raise ValueError("Completion response has no choices")
                text = self._extract_choice_text(choices[0], chat_mode=chat_mode)
                self._debug_raw("chat" if chat_mode else "completion", text)
                return _extract_json_object(text)
            except Exception as exc:
                last_exc = exc
                continue

        if last_exc is not None:
            raise last_exc
        raise RuntimeError("No completion mode succeeded")

    def healthcheck(self) -> None:
        url = f"{self.base_url}/v1/models"
        try:
            response = requests.get(url, headers=self._headers(), timeout=10)
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Cannot reach OpenAI-compatible API at {self.base_url!r}: {exc}"
            ) from exc
        if response.status_code == 401:
            raise RuntimeError(
                "API returned 401 Unauthorized. "
                "Set a valid DUALIFY_API_KEY or GROQ_API_KEY in the environment, "
                "or pass --api-key."
            )
        if response.status_code == 403:
            raise RuntimeError(
                "API returned 403 Forbidden. Check API key permissions and base URL."
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Health check failed ({response.status_code}): {response.text[:500]}"
            ) from exc


def create_llm_client(
    *,
    provider: str,
    model: str,
    base_url: str,
    api_key: str = "",
) -> LLMClient:
    normalized_base_url = base_url.rstrip("/")
    if provider == "ollama":
        return OllamaClient(model=model, base_url=normalized_base_url)
    if provider == "openai":
        if not (api_key or "").strip():
            raise ValueError(
                "Provider 'openai' requires an API key. "
                "Set DUALIFY_API_KEY or GROQ_API_KEY in .env, or pass --api-key."
            )
        if (
            "groq.com" in normalized_base_url
            or "sambanova.ai" in normalized_base_url
            or "openrouter.ai" in normalized_base_url
        ):
            profile = profile_for_base_url(normalized_base_url)
            assert profile is not None
            return OpenAICompatibleClient(
                model=model,
                base_url=normalized_base_url,
                api_key=api_key.strip(),
                timeout_sec=profile.timeout_sec,
                max_retries=profile.max_retries,
                backoff_base_sec=profile.backoff_base_sec,
                max_backoff_sec=profile.max_backoff_sec,
            )
        return OpenAICompatibleClient(
            model=model,
            base_url=normalized_base_url,
            api_key=api_key.strip(),
        )
    raise ValueError(f"Unsupported provider: {provider}")
