"""Preflight и dev campaign на фиксированном split RQ1."""

import argparse
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import replace
from functools import partial
from importlib.metadata import distributions
from pathlib import Path
from tempfile import TemporaryDirectory

import requests
from dotenv import load_dotenv

from dualify.discovery import discover_python_cases
from dualify.ollama_client import OpenAICompatibleClient, _extract_json_object
from dualify.rq1_attempt import AttemptRecord
from dualify.rq1_pool import (
    PoolIntegrityError,
    read_candidate_pool,
    run_candidate_pool,
    verify_candidate_pool,
)
from dualify.rq1_report import (
    BOOTSTRAP_RESAMPLES,
    BOOTSTRAP_SEED,
    AnalysisBlockedError,
    analyze_candidate_pools,
)

ROOT = Path(__file__).resolve().parents[2]
SPLIT = ROOT / "docs/rq1/benchmark-manifest.json"
BASE_URL = "https://api.groq.com/openai"
MODEL = "qwen/qwen3.8-27b"
TEMPERATURE = 0.7
CHANNELS = ("spec", "code")
TIMEOUT = 120
HTTP_CAP = 180
HTTP_ATTEMPTS = 2
TOKEN_CAP = 1024
THROTTLE_SECONDS = 18


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write(path: Path, payload: object) -> None:
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)


def _revision() -> str:
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True,
    )
    if dirty:
        raise ValueError("Preflight requires a clean source revision")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def _dependencies() -> dict[str, str]:
    return dict(sorted((d.metadata["Name"], d.version) for d in distributions()))


def _dev_split() -> tuple[int, list[dict]]:
    split = json.loads(SPLIT.read_text(encoding="utf-8"))
    dev = [row for row in split["cases"] if row["split"] == "dev"]
    if len(dev) != 10 or len({row["benchmark_id"] for row in dev}) != 10:
        raise ValueError("Expected 10 unique dev cases")
    return split["seed"], dev


def _preflight() -> dict:
    seed, dev = _dev_split()
    for row in dev:
        for kind in ("input", "gold"):
            if _sha256(ROOT / row[f"{kind}_path"]) != row[f"{kind}_sha256"]:
                raise ValueError(f"Checksum mismatch: {row[f'{kind}_path']}")
    return {
        "split_sha256": _sha256(SPLIT),
        "split_seed": seed,
        "source_commit": _revision(),
        "upstream_commit": "7ffd1ae37822096d5b7b573785ee46e877903185",
        "python": sys.version.splitlines()[0],
        "dependencies": _dependencies(),
        "sha256": {
            path: _sha256(ROOT / path)
            for path in (
                "poetry.lock", "pyproject.toml",
                "src/dualify/phases/p01_spec_to_logic.py",
                "src/dualify/phases/p02_code_to_logic.py",
                "src/dualify/phases/formula_prompt_rules.py",
                "src/dualify/phases/p03_smt_checking.py",
                "src/dualify/gold_scoring.py",
                "src/dualify/formula_parser.py",
                "src/dualify/rq1_report.py",
            )
        },
        "provider": "groq",
        "model": MODEL,
        "models_endpoint": f"{BASE_URL}/v1/models",
        "endpoint": f"{BASE_URL}/v1/chat/completions",
        "reasoning_effort": "none",
        "response_format": "json_object",
        "top_p": "provider default (1)",
        "baseline_temperature": 0,
        "repair_temperature": 0,
        "treatment_temperature": TEMPERATURE,
        "request_timeout_seconds": TIMEOUT,
        "max_output_tokens": TOKEN_CAP,
        "max_campaign_posts": HTTP_CAP,
        "max_http_attempts_per_call": HTTP_ATTEMPTS,
        "max_outer_retries": 0,
        "backoff_seconds": {"base": 2, "max": 60, "use_retry_after": True},
        "min_seconds_between_posts": THROTTLE_SECONDS,
        "public_free_plan": {"rpm": 30, "rpd": 1000, "tpm": 8000, "tpd": 200000},
        "limits_source": "https://console.groq.com/docs/rate-limits",
        "temperature_source": "https://huggingface.co/Qwen/Qwen3.8-27B",
        "oracle_timeout_seconds": 5,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "bootstrap_resamples": BOOTSTRAP_RESAMPLES,
        "k": [1, 2, 4],
        "dev_cases": dev,
        "planned_slots": [
            f"{row['benchmark_id']}:{channel}:{arm}:{index}"
            for row in dev for channel in CHANNELS
            for arm, index in (("baseline", 0), *(("treatment", i) for i in range(1, 5)))
        ],
    }


def _check_model(directory: Path, manifest: dict, api_key: str) -> None:
    evidence = directory / "models-check.json"
    if evidence.exists():
        if json.loads(evidence.read_text()).get("model_available") is True:
            return
        raise ValueError("Previous Groq models preflight did not confirm access")
    _write(evidence, {"status": "request_started"})
    response = requests.get(
        manifest["models_endpoint"], headers={"Authorization": f"Bearer {api_key}"},
        timeout=TIMEOUT, allow_redirects=False,
    )
    if response.status_code != 200:
        _write(evidence, {
            "status": response.status_code,
            "body": response.text.replace(api_key, "[REDACTED]"),
        })
        raise ValueError(f"Groq models endpoint returned HTTP {response.status_code}")
    available = any(row["id"] == MODEL for row in response.json()["data"])
    _write(evidence, {"status": 200, "model_available": available})
    if not available:
        raise ValueError(f"model unavailable in Groq account: {MODEL}")


class CampaignTransport:
    """Считает физические POST, включая retry, и связывает их с текущим slot."""

    def __init__(self, directory: Path, api_key: str) -> None:
        self.directory = directory
        self.directory.mkdir(exist_ok=True)
        self.api_key = api_key
        self.sent = len(list(directory.glob("*.json")))
        self.next_post = time.monotonic() + (THROTTLE_SECONDS if self.sent else 0)
        self.slot_id = ""
        self.attempt = 0

    def start_slot(self, slot_id: str, *, pool: Path) -> None:
        self.slot_id = slot_id
        self.attempt = self.sent + 1
        previous_failure = pool / slot_id.replace(":", "__") / "failure.json"
        if previous_failure.exists():
            # A crash during this dispatch must not inherit the previous diagnosis.
            previous_failure.rename(
                previous_failure.with_name(f"failure-before-{self.attempt:04d}.json"),
            )

    def post(self, url: str, *, json: dict, headers: dict, timeout: int) -> requests.Response:
        if self.sent >= HTTP_CAP:
            raise ValueError(f"Campaign HTTP budget exhausted ({HTTP_CAP} POSTs)")
        time.sleep(max(0.0, self.next_post - time.monotonic()))
        self.next_post = time.monotonic() + THROTTLE_SECONDS
        self.sent += 1
        path = self.directory / f"{self.sent:04d}.json"
        evidence = {"slot_id": self.slot_id, "attempt": self.attempt, "payload": json}
        _write(path, evidence)
        try:
            response = requests.post(
                url, json=json, headers=headers, timeout=timeout, allow_redirects=False,
            )
        except requests.RequestException as exc:
            _write(path, {**evidence, "transport_error": str(exc).replace(
                self.api_key, "[REDACTED]",
            )})
            raise
        _write(path, {
            **evidence,
            "status": response.status_code,
            "body": response.text.replace(self.api_key, "[REDACTED]"),
            "headers": {
                name.lower(): value for name, value in response.headers.items()
                if name.lower().startswith("x-ratelimit-")
                or name.lower() in {"retry-after", "x-request-id", "x-groq-request-id"}
            },
        })
        return response


def _pool_dir(directory: Path, row: dict) -> Path:
    return directory / "pools" / Path(row["input_path"]).stem


def _http_by_slot(directory: Path, manifest: dict) -> dict[str, list[dict]]:
    paths = sorted((directory / "http").glob("*.json"))
    if len(paths) > manifest["max_campaign_posts"]:
        raise ValueError("Saved HTTP evidence exceeds the frozen campaign budget")
    by_slot: dict[str, list[dict]] = {}
    planned = set(manifest["planned_slots"])
    for index, path in enumerate(paths, 1):
        row = json.loads(path.read_text())
        if path.name != f"{index:04d}.json" or row["slot_id"] not in planned:
            raise ValueError(f"Unexpected HTTP evidence: {path}")
        by_slot.setdefault(row["slot_id"], []).append(row)
    return by_slot


def _run(directory: Path, manifest: dict, api_key: str) -> None:
    contacted = _http_by_slot(directory, manifest)
    transport = CampaignTransport(directory / "http", api_key)
    client = OpenAICompatibleClient(
        MODEL, BASE_URL, api_key, timeout_sec=TIMEOUT, max_retries=HTTP_ATTEMPTS,
        backoff_base_sec=2, max_backoff_sec=60, fixed_chat_mode=True,
        reasoning_effort="none", max_tokens=TOKEN_CAP, post=transport.post,
    )
    cases = discover_python_cases(ROOT / "benchmark/lifted_auto_eval", ROOT)
    for row in manifest["dev_cases"]:
        case_id = row["benchmark_id"]
        matches = [
            case for case in cases if case.file == row["input_path"]
            and case_id.endswith("::" + case.qualname.replace(".", "::"))
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected exactly one discovered entry for {case_id}")
        pool = _pool_dir(directory, row)
        for slot in manifest["planned_slots"]:
            if slot.rsplit(":", 3)[0] != case_id:
                continue
            slot_dir = pool / slot.replace(":", "__")
            if (slot_dir / "result.json").exists():
                continue
            failure = slot_dir / "failure.json"
            if failure.exists():
                errors = json.loads(failure.read_text())["errors"]
                if not errors or errors[-1]["category"] != "transient_infrastructure":
                    raise ValueError(f"Cannot resume non-infrastructure failure: {failure}")
            elif slot in contacted:
                raise ValueError(f"{slot}: HTTP evidence without infrastructure diagnosis")
        case = replace(matches[0], benchmark_id=case_id)
        records = run_candidate_pool(
            client, case=case, artifact_dir=pool, model=MODEL, provider="groq",
            treatment_temperature=TEMPERATURE,
            on_slot_started=partial(transport.start_slot, pool=pool),
        )
        if records[-1].status != "completed":
            last = records[-1]
            detail = last.errors[-1].message if last.errors else last.status
            raise ValueError(f"{last.slot_id}: {last.status}: {detail}")
        verify_candidate_pool(
            artifact_dir=pool, case=case, model=MODEL, provider="groq",
            treatment_temperature=TEMPERATURE,
        )
        print(f"Completed pool: {case_id}", flush=True)


def verify_http(
    directory: Path, manifest: dict, records: Sequence[AttemptRecord],
) -> dict:
    """Проверяет физические ответы Groq для сохранённых completed slots."""
    by_slot = _http_by_slot(directory, manifest)
    statuses = Counter(
        str(row.get("status", "transport_error"))
        for rows in by_slot.values() for row in rows
    )
    completions = set()
    response_tokens = 0
    token_observations = 0
    for record in records:
        slot = record.slot_id
        rows = by_slot.get(slot, [])
        if not rows:
            raise ValueError(f"Missing HTTP evidence for {slot}")
        # Старые записи одной непрерывной кампании не имеют индекса resume.
        last_attempt = rows[-1].get("attempt")
        latest = [row for row in rows if row.get("attempt") == last_attempt]
        index_in_attempt = 0
        for call in record.calls:
            allowed_format_errors = {
                error.status_code for error in record.errors
                if error.call_index == call.index and error.category == "model_output_format"
            }
            for _ in range(manifest["max_http_attempts_per_call"]):
                if index_in_attempt >= len(latest):
                    raise ValueError(f"Missing HTTP evidence for {slot} call {call.index}")
                row = latest[index_in_attempt]
                index_in_attempt += 1
                payload = row["payload"]
                if (
                    payload.get("model") != manifest["model"]
                    or payload.get("temperature") != call.temperature
                    or payload.get("reasoning_effort") != manifest["reasoning_effort"]
                    or payload.get("max_tokens") != manifest["max_output_tokens"]
                    or payload.get("response_format") != {"type": manifest["response_format"]}
                ):
                    raise ValueError(f"HTTP request differs from frozen settings: {slot}")
                status = row.get("status")
                if status == 200:
                    body = json.loads(row["body"])
                    completion_id = body.get("id")
                    if not completion_id or body.get("model") != manifest["model"]:
                        raise ValueError(f"Missing Groq completion ID or unexpected model: {slot}")
                    if completion_id in completions:
                        raise ValueError(f"Duplicate Groq completion ID: {completion_id}")
                    completions.add(completion_id)
                    try:
                        content = body["choices"][0]["message"]["content"]
                        parsed = _extract_json_object(content)
                    except json.JSONDecodeError:
                        if None not in allowed_format_errors or call.response is not None:
                            raise ValueError(f"Unexpected malformed Groq output: {slot}") from None
                    else:
                        if parsed != call.response:
                            raise ValueError(f"Groq response differs from saved candidate: {slot}")
                    tokens = body.get("usage", {}).get("completion_tokens")
                    if isinstance(tokens, int):
                        token_observations += 1
                        response_tokens += tokens
                    break
                if status in allowed_format_errors and call.response is None and status in (
                    400, 422,
                ):
                    break
                if "transport_error" not in row and status not in (429, 500, 502, 503, 504):
                    raise ValueError(f"Unclassified HTTP evidence for {slot} call {call.index}")
            else:
                raise ValueError(f"Missing model response for {slot} call {call.index}")
        if index_in_attempt != len(latest):
            raise ValueError(f"Unexpected additional HTTP calls for {slot}")
    return {
        "verified_slots": len(records),
        "http_posts": statuses.total(),
        "http_statuses": dict(statuses),
        "unique_groq_completion_ids": len(completions),
        "observed_completion_tokens": response_tokens,
        "completion_token_observations": token_observations,
    }


def _score(directory: Path, manifest: dict, output: Path) -> None:
    _, dev = _dev_split()
    if manifest["split_sha256"] != _sha256(SPLIT) or manifest["dev_cases"] != dev:
        raise ValueError("Saved campaign does not match the frozen dev split")
    for path, digest in manifest["sha256"].items():
        if _sha256(ROOT / path) != digest:
            raise ValueError(f"Frozen source checksum mismatch: {path}")
    if _dependencies().get("z3-solver") != manifest["dependencies"]["z3-solver"]:
        raise ValueError("Installed Z3 version differs from the frozen campaign")
    pools = [_pool_dir(directory, row) for row in dev]
    records = [record for pool in pools for record in read_candidate_pool(pool)[1]]
    http = verify_http(directory, manifest, records)
    # Даём исходному scorer только gold из dev, после сохранения generation records.
    with TemporaryDirectory() as gold:
        gold_dir = Path(gold)
        for row in dev:
            path = ROOT / row["gold_path"]
            if _sha256(path) != row["gold_sha256"]:
                raise ValueError(f"Gold checksum mismatch: {path}")
            (gold_dir / path.name).symlink_to(path)
        tasks, summary = analyze_candidate_pools(pools, gold_dir=gold_dir)
    expected = {
        "model": manifest["model"],
        "provider": manifest["provider"],
        "treatment_temperature": manifest["treatment_temperature"],
        "max_transient_retries": manifest["max_outer_retries"],
        "endpoint_sha256": hashlib.sha256(manifest["endpoint"].encode()).hexdigest(),
    }
    if summary["sampling"] != expected:
        raise ValueError("Saved pools do not match the frozen sampling configuration")
    output.mkdir(parents=True, exist_ok=True)
    _write(output / "tasks.json", tasks)
    _write(output / "summary.json", summary)
    _write(output / "http-summary.json", http)


def _recorded_slots(directory: Path, planned: list[str]) -> tuple[set[str], list[str]]:
    expected = set(planned)
    completed = set()
    invalid = []
    for path in sorted(directory.glob("pools/*/*/result.json")):
        try:
            record = json.loads(path.read_text())
            slot = record["slot_id"]
            if (
                record["status"] != "completed" or slot not in expected or slot in completed
                or path.parent.name != slot.replace(":", "__")
            ):
                raise ValueError("Unexpected completed slot")
        except (OSError, ValueError, KeyError, TypeError):
            invalid.append(str(path.relative_to(directory)))
        else:
            completed.add(slot)
    return completed, invalid


def _live(directory: Path) -> int:
    manifest: dict = {}
    started = time.monotonic()
    verdict = "BLOCKED"
    reason = ""
    try:
        manifest = _preflight()
        path = directory / "preflight.json"
        if path.exists() and json.loads(path.read_text()) != manifest:
            raise ValueError("Preflight differs from the recorded campaign")
        _write(path, manifest)
        load_dotenv(ROOT / ".env")
        api_key = os.environ.get("GROQ_API_KEY", "").strip()
        if not api_key:
            raise ValueError("GROQ_API_KEY is missing")
        _check_model(directory, manifest, api_key)
        _run(directory, manifest, api_key)
        _score(directory, manifest, directory / "report")
        verdict = "DEV COMPLETE"
    except (
        OSError, ValueError, KeyError, requests.RequestException, AnalysisBlockedError,
        PoolIntegrityError, subprocess.CalledProcessError,
    ) as exc:
        reason = str(exc)
        print(f"BLOCKED: {exc}", file=sys.stderr)
    except KeyboardInterrupt:
        reason = "Dev campaign interrupted"
        raise
    finally:
        planned = manifest.get("planned_slots", [])
        completed, invalid = _recorded_slots(directory, planned)
        if invalid:
            verdict = "BLOCKED"
            reason = reason or "Invalid completed slot records"
        _write(directory / "gate.json", {
            "verdict": verdict,
            "reason": reason,
            "completed_slots": sorted(completed),
            "missing_slots": [
                slot for slot in planned if slot not in completed
            ],
            "invalid_result_paths": invalid,
            "http_posts": len(list(directory.glob("http/*.json"))),
            "invocation_elapsed_seconds": time.monotonic() - started,
        })
    return int(verdict == "BLOCKED")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--offline", type=Path, metavar="REPORT_DIR")
    args = parser.parse_args(argv)
    directory = args.output
    try:
        if args.offline:
            manifest = json.loads((directory / "preflight.json").read_text())
            _score(directory, manifest, args.offline)
            return 0
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / ".campaign.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return _live(directory)
    except BlockingIOError:
        print("BLOCKED: campaign directory is in use", file=sys.stderr)
    except (
        OSError, ValueError, KeyError, TypeError, AnalysisBlockedError, PoolIntegrityError,
    ) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
