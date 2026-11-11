import json
import os
import time
from dataclasses import dataclass, field
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
    json_mode_max_attempts: int = 3
    json_validation_failures: int = field(default=0, init=False)
    json_retry_requests: int = field(default=0, init=False)
    json_retry_recoveries: int = field(default=0, init=False)
    json_retry_exhaustions: int = field(default=0, init=False)

    def retry_diagnostics(self) -> dict[str, object]:
        """Only live Groq JSON-mode retries are counted, not transcript replays."""
        return {
            "json_validate_failed": {
                "trigger": "Groq chat HTTP 400 with code/type json_validate_failed",
                "max_attempts": self.json_mode_max_attempts,
                "validation_error_responses": self.json_validation_failures,
                "additional_requests": self.json_retry_requests,
                "recovered_calls": self.json_retry_recoveries,
                "exhausted_calls": self.json_retry_exhaustions,
            }
        }

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

    @staticmethod
    def _api_error_detail(response: requests.Response) -> str:
        """Show the provider's error message without logging the prompt or API key."""
        try:
            data = response.json()
        except (ValueError, requests.RequestException):
            data = None
        if isinstance(data, dict):
            error = data.get("error", data)
            if isinstance(error, dict):
                message = error.get("message", "")
                code = error.get("code") or error.get("type")
                detail = f"{code}: {message}" if code else str(message)
            else:
                detail = str(error)
        else:
            detail = response.text or "No error details returned"
        return " ".join(detail.split())[:1200]

    @staticmethod
    def _is_json_validation_failure(response: requests.Response) -> bool:
        if response.status_code != 400:
            return False
        try:
            body = response.json()
        except (ValueError, requests.RequestException):
            return False
        error = body.get("error") if isinstance(body, dict) else None
        return isinstance(error, dict) and (
            error.get("code") == "json_validate_failed"
            or error.get("type") == "json_validate_failed"
        )

    def _post_groq_json_with_retry(self, url: str, payload: dict) -> requests.Response:
        """Retry only the intermittent Groq JSON-validation response."""
        for attempt in range(1, self.json_mode_max_attempts + 1):
            response = self._post_with_retry(url, payload)
            if not self._is_json_validation_failure(response):
                if attempt > 1 and response.ok:
                    self.json_retry_recoveries += 1
                    print(
                        f"[dualify-llm] Groq JSON request recovered on attempt {attempt}",
                        flush=True,
                    )
                return response
            self.json_validation_failures += 1
            if attempt == self.json_mode_max_attempts:
                self.json_retry_exhaustions += 1
                print(
                    f"[dualify-llm] Groq JSON validation failed after {attempt} attempts",
                    flush=True,
                )
                return response
            self.json_retry_requests += 1
            print(
                f"[dualify-llm] Groq json_validate_failed "
                f"(attempt {attempt}/{self.json_mode_max_attempts}); retrying",
                flush=True,
            )
        raise AssertionError("unreachable: JSON attempt count must be positive")

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
                if attempt == self.max_retries - 1:
                    break
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
                # The last attempt has already failed: don't sleep needlessly.
                if attempt == self.max_retries - 1:
                    return response
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
        # Groq only supports chat completions. Keep payloads unchanged so
        # previously recorded successful response transcripts remain replayable.
        is_groq = "groq.com" in self.base_url.lower()
        prefer_chat = self._prefers_chat_mode()
        attempts = [True] if is_groq else ([True, False] if prefer_chat else [False, True])
        errors: list[str] = []
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
                if is_groq and chat_mode:
                    response = self._post_groq_json_with_retry(url, payload)
                else:
                    response = self._post_with_retry(url, payload)
                response.raise_for_status()
                body = response.json()
                choices = body.get("choices", [])
                if not isinstance(choices, list) or not choices:
                    raise ValueError("Completion response has no choices")
                choice = choices[0]
                if choice.get("finish_reason") == "length":
                    raise ValueError("Output truncated at max_tokens=1024")
                generated = self._extract_choice_text(choice, chat_mode=chat_mode)
                self._debug_raw("chat" if chat_mode else "completion", generated)
                return _extract_json_object(generated)
            except requests.HTTPError as exc:
                last_exc = exc
                response = exc.response
                if response is None:
                    errors.append(f"{endpoint}: {exc}")
                    continue
                detail = self._api_error_detail(response)
                errors.append(f"{endpoint}: HTTP {response.status_code}: {detail}")
                # Authentication and exhausted rate limits aren't fixed by
                # switching from text completions to chat (or vice versa).
                if response.status_code in (401, 403, 429):
                    raise RuntimeError(
                        "LLM API request failed after retries:\n  "
                        + "\n  ".join(errors)
                    ) from exc
            except requests.RequestException as exc:
                last_exc = exc
                errors.append(f"{endpoint}: {type(exc).__name__}: {exc}")
                break
            except (ValueError, TypeError, KeyError) as exc:
                last_exc = exc
                errors.append(f"{endpoint}: {type(exc).__name__}: {exc}")

        raise RuntimeError(
            "LLM API request failed:\n  " + "\n  ".join(errors)
        ) from last_exc

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
