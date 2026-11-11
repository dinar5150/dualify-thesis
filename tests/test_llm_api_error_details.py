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


def test_shows_both_endpoint_errors(monkeypatch):
    calls = []

    def post(url, **kwargs):
        calls.append(url)
        if url.endswith("/v1/completions"):
            return _response(404, "Text completions endpoint not available")
        return _response(400, "JSON mode request rejected for this prompt")

    monkeypatch.setattr(requests, "post", post)
    client = OpenAICompatibleClient(
        "qwen/qwen3.8-27b", "https://api.groq.com/openai", max_retries=1
    )
    with pytest.raises(RuntimeError) as caught:
        client.generate_json("Give a JSON object", temperature=0.7)
    message = str(caught.value)
    assert "/v1/completions: HTTP 404" in message
    assert "/v1/chat/completions: HTTP 400" in message
    assert "JSON mode request rejected" in message
    assert len(calls) == 2


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
        response._content = b'{"choices":[{"text":"{\\"answer\\": 42}"}]}'
        response.url = url
        return response

    monkeypatch.setattr(requests, "post", post)
    client = OpenAICompatibleClient(
        "qwen/qwen3.8-27b", "https://api.groq.com/openai", max_retries=1
    )
    result = client.generate_json("Provide JSON", temperature=0.7)
    assert result == {"answer": 42}
    assert sent[0][1]["temperature"] == 0.7
    assert sent[0][1]["prompt"] == "Provide JSON"
    assert sent[0][0].endswith("/v1/completions")
