import json

import pytest
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


def test_resume_passes_old_post_cap_and_preserves_original_preflight(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "offline-fixture")
    monkeypatch.setattr(rq1_dev, "_revision", lambda: "a" * 40)
    monkeypatch.setattr(rq1_dev, "_dependencies", lambda: {"z3-solver": "fixture"})
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
    preflight = tmp_path / "preflight.json"
    original = json.loads(preflight.read_text())
    original["max_campaign_posts"] = 2
    preflight.write_text(json.dumps(original))
    original_bytes = preflight.read_bytes()
    monkeypatch.setattr(rq1_dev, "_revision", lambda: "b" * 40)

    assert rq1_dev.main([str(tmp_path)]) == 1
    gate = json.loads((tmp_path / "gate.json").read_text())
    assert len(posts) == 4
    assert posts[2]["reasoning_effort"] == "none"
    assert posts[2]["temperature"] == 0
    assert gate["http_posts"] == 4
    assert gate["completed_slots"] == []
    assert len(gate["missing_slots"]) == 100
    assert preflight.read_bytes() == original_bytes
    resume = json.loads((tmp_path / "resume-preflight.json").read_text())
    assert resume["source_commit"] == "b" * 40
    assert resume["max_campaign_posts"] is None
    evidence = json.loads((tmp_path / "http/0003.json").read_text())
    assert evidence["slot_id"] == gate["missing_slots"][0]
    assert evidence["status"] == 503
    assert "temporarily unavailable" in evidence["body"]
    assert "offline-fixture" not in (tmp_path / "http/0003.json").read_text()


def test_corrupt_candidate_cannot_hide_blocked_gate(tmp_path, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setattr(rq1_dev, "load_dotenv", lambda *args: None)
    monkeypatch.setattr(rq1_dev, "_revision", lambda: "a" * 40)
    record = tmp_path / "pools" / "corrupt" / "slot" / "result.json"
    record.parent.mkdir(parents=True)
    record.write_text("{broken")

    assert rq1_dev.main([str(tmp_path)]) == 1
    gate = json.loads((tmp_path / "gate.json").read_text())
    assert gate["verdict"] == "BLOCKED"
    assert gate["completed_slots"] == []
    assert len(gate["missing_slots"]) == 100
    assert gate["invalid_result_paths"] == ["pools/corrupt/slot/result.json"]


def test_resume_blocks_interrupted_post_without_infrastructure_diagnosis(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "offline-fixture")
    monkeypatch.setattr(rq1_dev, "_revision", lambda: "a" * 40)
    (tmp_path / "models-check.json").write_text('{"model_available": true}')
    http = tmp_path / "http"
    http.mkdir()
    slot = "crosshair_examples::PEP316::correct_code::arith.py::swap:spec:baseline:0"
    (http / "0001.json").write_text(json.dumps({"slot_id": slot, "status": 200}))

    def unexpected_post(*args, **kwargs):
        raise AssertionError("An ambiguous earlier generation must not be repeated")

    monkeypatch.setattr(requests, "post", unexpected_post)

    assert rq1_dev.main([str(tmp_path)]) == 1
    gate = json.loads((tmp_path / "gate.json").read_text())
    assert slot in gate["reason"]
    assert "without infrastructure diagnosis" in gate["reason"]
    assert gate["http_posts"] == 1


def test_http_evidence_rejects_missing_or_duplicate_provider_completions(tmp_path):
    from dualify.rq1_attempt import AttemptRecord, LogicalCall
    from dualify.types import ExtractionResult

    def candidate(index):
        return AttemptRecord(
            slot_id=f"increment:spec:treatment:{index}",
            channel="spec", model="qwen/qwen3.8-27b", initial_temperature=0.7,
            repair_temperature=0, max_transient_retries=0, status="completed",
            extraction=ExtractionResult("increment", ["x"], "int", [], "ret == x + 1", "high", ""),
            calls=[LogicalCall(0, "initial", 0.7, 1, {"postcondition": "ret == x + 1"})],
            errors=[], elapsed_seconds=1,
        )

    candidates = [candidate(1), candidate(2)]
    manifest = {
        "model": "qwen/qwen3.8-27b",
        "reasoning_effort": "none",
        "response_format": "json_object",
        "max_output_tokens": 1024,
        "max_http_attempts_per_call": 2,
        "max_campaign_posts": 180,
        "planned_slots": [record.slot_id for record in candidates],
    }
    http = tmp_path / "http"
    http.mkdir()

    def receipt(index, completion_id):
        (http / f"{index:04d}.json").write_text(json.dumps({
            "slot_id": candidates[index - 1].slot_id,
            "status": 200,
            "payload": {
                "model": "qwen/qwen3.8-27b", "temperature": 0.7, "reasoning_effort": "none",
                "max_tokens": 1024, "response_format": {"type": "json_object"},
            },
            "body": json.dumps({
                "id": completion_id,
                "model": "qwen/qwen3.8-27b",
                "choices": [{"message": {"content": '{"postcondition": "ret == x + 1"}'}}],
            }),
        }))

    receipt(1, "chatcmpl-1")
    with pytest.raises(ValueError, match="Missing HTTP evidence.*treatment:2"):
        rq1_dev.verify_http(tmp_path, manifest, candidates)
    receipt(2, "chatcmpl-1")
    with pytest.raises(ValueError, match="Duplicate Groq completion ID"):
        rq1_dev.verify_http(tmp_path, manifest, candidates)
    receipt(2, "chatcmpl-2")
    assert rq1_dev.verify_http(tmp_path, manifest, candidates)["verified_slots"] == 2


def test_interrupted_resume_cannot_reuse_previous_failure_as_diagnosis(tmp_path, monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "offline-fixture")
    monkeypatch.setattr(rq1_dev, "_revision", lambda: "a" * 40)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    (tmp_path / "models-check.json").write_text('{"model_available": true}')
    posts = 0

    def post(*args, **kwargs):
        nonlocal posts
        posts += 1
        if posts == 3:
            raise KeyboardInterrupt
        response = requests.Response()
        response.status_code = 503
        response._content = b'{"error":{"message":"Service temporarily unavailable"}}'
        return response

    monkeypatch.setattr(requests, "post", post)
    assert rq1_dev.main([str(tmp_path)]) == 1
    with pytest.raises(KeyboardInterrupt):
        rq1_dev.main([str(tmp_path)])
    assert rq1_dev.main([str(tmp_path)]) == 1
    gate = json.loads((tmp_path / "gate.json").read_text())
    assert "without infrastructure diagnosis" in gate["reason"]
    assert posts == 3
