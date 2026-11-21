import json

import requests

from dualify import rq1_dev


def test_preflight_blocks_unavailable_model_before_generation(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "offline-fixture")
    monkeypatch.setattr(rq1_dev, "_revision", lambda: "a" * 40)
    monkeypatch.setattr(rq1_dev, "_dependencies", lambda: {"z3-solver": "fixture"})

    def models(url, **kwargs):
        assert url == "https://api.groq.com/openai/v1/models"
        manifest = json.loads((tmp_path / "preflight.json").read_text())
        assert manifest["model"] == "qwen/qwen3.8-27b"
        assert manifest["treatment_temperature"] == 0.7
        assert len(manifest["planned_slots"]) == 100
        response = requests.Response()
        response.status_code = 200
        response._content = b'{"data": [{"id": "other-model"}]}'
        return response

    def unexpected_post(*args, **kwargs):
        raise AssertionError("Generation must wait for a successful preflight")

    monkeypatch.setattr(requests, "get", models)
    monkeypatch.setattr(requests, "post", unexpected_post)

    assert rq1_dev.main([str(tmp_path)]) == 1
    gate = json.loads((tmp_path / "gate.json").read_text())
    assert gate["verdict"] == "BLOCKED"
    assert gate["completed_slots"] == []
    assert len(gate["missing_slots"]) == 100
    assert "model unavailable" in gate["reason"]


def test_http_cap_counts_retries_and_preserves_incomplete_slot(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "offline-fixture")
    monkeypatch.setattr(rq1_dev, "_revision", lambda: "a" * 40)
    monkeypatch.setattr(rq1_dev, "_dependencies", lambda: {"z3-solver": "fixture"})
    monkeypatch.setattr(rq1_dev, "HTTP_CAP", 1, raising=False)
    monkeypatch.setattr("time.sleep", lambda seconds: None)

    model_response = requests.Response()
    model_response.status_code = 200
    model_response._content = b'{"data":[{"id":"qwen/qwen3.8-27b"}]}'
    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: model_response)
    posts = []

    def post(url, *, json, **kwargs):
        posts.append(json)
        response = requests.Response()
        response.status_code = 503
        response._content = b'{"error":{"message":"Service temporarily unavailable"}}'
        return response

    monkeypatch.setattr(requests, "post", post)

    assert rq1_dev.main([str(tmp_path)]) == 1
    gate = json.loads((tmp_path / "gate.json").read_text())
    assert len(posts) == 1
    assert posts[0]["reasoning_effort"] == "none"
    assert posts[0]["temperature"] == 0
    assert gate["http_posts"] == 1
    assert gate["completed_slots"] == []
    assert len(gate["missing_slots"]) == 100
    evidence = json.loads((tmp_path / "http/0001.json").read_text())
    assert evidence["slot_id"] == gate["missing_slots"][0]
    assert evidence["status"] == 503
    assert "temporarily unavailable" in evidence["body"]
    assert "offline-fixture" not in (tmp_path / "http/0001.json").read_text()
