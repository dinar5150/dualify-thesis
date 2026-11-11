"""No network required: provider errors should explain why a run stopped."""

import json

import pytest
import requests

from dualify.ollama_client import OpenAICompatibleClient


def _response(status: int, detail: str) -> requests.Response:
    response = requests.Response()
    response.status_code = status
    response.url = "https://api.groq.com/openai/v1/chat/completions"
    response._content = json.dumps(
        {"error": {"message": detail, "type": "invalid_request_error"}}
    ).encode()
    return response


def test_groq_uses_chat_only_even_when_chat_preference_is_disabled(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return _response(400, "JSON mode request rejected for this prompt")

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setenv("DUALIFY_OPENAI_USE_CHAT", "0")
    client = OpenAICompatibleClient(
        "qwen/qwen3.8-27b", "https://api.groq.com/openai", max_retries=1
    )
    with pytest.raises(RuntimeError) as caught:
        client.generate_json("Give a JSON object", temperature=0.7)
    message = str(caught.value)
    assert "/v1/chat/completions: HTTP 400" in message
    assert "JSON mode request rejected" in message
    assert calls == ["https://api.groq.com/openai/v1/chat/completions"]


def test_exhausted_rate_limit_does_not_try_other_endpoint_or_sleep(monkeypatch):
    calls = []
    sleeps = []

    def post(url, **kwargs):
        calls.append(url)
        return _response(429, "Rate limit exceeded")

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.setattr("dualify.ollama_client.time.sleep", sleeps.append)
    client = OpenAICompatibleClient(
        "qwen/qwen3.8-27b", "https://api.groq.com/openai", max_retries=1
    )
    with pytest.raises(RuntimeError, match="Rate limit exceeded"):
        client.generate_json("Give a JSON object", temperature=0.7)
    assert len(calls) == 1
    assert sleeps == []


def test_successful_request_preserves_prompt_temperature_and_output(monkeypatch):
    sent = []

    def post(url, *, json, **kwargs):
        sent.append((url, json))
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"choices":[{"message":{"content":"{\\"answer\\": 42}"}}]}'
        response.url = url
        return response

    monkeypatch.setattr(requests, "post", post)
    client = OpenAICompatibleClient(
        "qwen/qwen3.8-27b", "https://api.groq.com/openai", max_retries=1
    )
    result = client.generate_json("Provide JSON", temperature=0.7)
    assert result == {"answer": 42}
    assert sent[0][1]["temperature"] == 0.7
    assert sent[0][1]["messages"][1]["content"] == "Provide JSON"
    assert sent[0][1]["response_format"] == {"type": "json_object"}
    assert sent[0][0].endswith("/v1/chat/completions")



def _groq_validation_error() -> requests.Response:
    response = _response(400, "Failed to generate JSON")
    response._content = json.dumps({
        "error": {
            "code": "json_validate_failed",
            "message": "Failed to generate JSON",
            "failed_generation": "not valid JSON from model",
        }
    }).encode()
    return response


def _chat_success() -> requests.Response:
    response = requests.Response()
    response.status_code = 200
    response.url = "https://api.groq.com/openai/v1/chat/completions"
    response._content = b'{"choices":[{"message":{"content":"{\\"ok\\": true}"}}]}'
    return response


def test_groq_json_error_retries_identical_payload_and_recovers(monkeypatch):
    sent = []
    responses = [_groq_validation_error(), _groq_validation_error(), _chat_success()]

    def post(url, *, json, **kwargs):
        sent.append((url, json))
        return responses.pop(0)

    monkeypatch.setattr(requests, "post", post)
    client = OpenAICompatibleClient(
        "qwen/qwen3.8-27b", "https://api.groq.com/openai", max_retries=1
    )
    assert client.generate_json("Repair the JSON", temperature=0.7) == {"ok": True}
    assert len(sent) == 3
    assert all(url.endswith("/v1/chat/completions") for url, _ in sent)
    assert sent[0][1] == sent[1][1] == sent[2][1]
    assert sent[0][1]["temperature"] == 0.7
    stats = client.retry_diagnostics()["json_validate_failed"]
    assert stats["validation_error_responses"] == 2
    assert stats["additional_requests"] == 2
    assert stats["recovered_calls"] == 1
    assert stats["exhausted_calls"] == 0


def test_groq_json_error_exhaustion_reports_error_without_model_output(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return _groq_validation_error()

    monkeypatch.setattr(requests, "post", post)
    client = OpenAICompatibleClient(
        "qwen/qwen3.8-27b", "https://api.groq.com/openai", max_retries=1
    )
    with pytest.raises(RuntimeError, match="json_validate_failed") as caught:
        client.generate_json("Repair the JSON", temperature=0.7)
    assert "not valid JSON from model" not in str(caught.value)
    assert len(calls) == 3
    stats = client.retry_diagnostics()["json_validate_failed"]
    assert stats["validation_error_responses"] == 3
    assert stats["additional_requests"] == 2
    assert stats["recovered_calls"] == 0
    assert stats["exhausted_calls"] == 1


def test_other_groq_400_not_retried(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        return _response(400, "Bad request for another reason")

    monkeypatch.setattr(requests, "post", post)
    client = OpenAICompatibleClient(
        "qwen/qwen3.8-27b", "https://api.groq.com/openai", max_retries=1
    )
    with pytest.raises(RuntimeError, match="Bad request"):
        client.generate_json("Repair the JSON", temperature=0.7)
    assert len(calls) == 1


def test_non_groq_endpoint_fallback_unchanged(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        if url.endswith("/v1/chat/completions"):
            return _response(404, "Chat endpoint missing")
        response = requests.Response()
        response.status_code = 200
        response.url = url
        response._content = b'{"choices":[{"text":"{\\"ok\\": true}"}]}'
        return response

    monkeypatch.setattr(requests, "post", post)
    monkeypatch.delenv("DUALIFY_OPENAI_USE_CHAT", raising=False)
    client = OpenAICompatibleClient(
        "test-model", "https://api.example.com/openai", max_retries=1
    )
    assert client.generate_json("Return JSON") == {"ok": True}
    assert [url.split("/openai")[1] for url in calls] == [
        "/v1/chat/completions", "/v1/completions"
    ]
