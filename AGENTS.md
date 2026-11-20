# Repository agent guide

## Purpose
This repository is a documentation-first workspace for the bachelor thesis study of **Dualify RQ1**: how the probability of obtaining at least one gold-equivalent formal contract changes as the number of independently generated candidates increases. The project extends the **original** Dualify extraction workflow without changing its semantics.

**Source baseline:** [timur-harin/dualify](https://github.com/timur-harin/dualify), upstream commit `7ffd1ae37822096d5b7b573785ee46e877903185`.
**Current stage:** approved design and implementation tickets; this documentation branch does **not** authorize running implementation or live experiments in the current handoff. The existing fork branches are unrelated drafts; this branch starts from the upstream commit.

## Workflow for an AI coding agent
1. Read [docs/rq1/SPEC.md](docs/rq1/SPEC.md) and [CONTEXT.md](CONTEXT.md) before planning RQ1 changes.
2. Read [PROJECT_DECISIONS.md](PROJECT_DECISIONS.md) whenever choosing architecture, experiment protocol, evaluation, or trade-offs. Preserve approved decisions; propose an explicit amendment instead of silently changing them.
3. Choose **one unblocked ticket** from [docs/rq1/tickets/README.md](docs/rq1/tickets/README.md); read its complete file, including **Stopping criteria**.
4. Study the current source and tests at the relevant seam. Prefer the existing extractor, transcript and gold-scoring interfaces. Add the narrowest observable end-to-end slice, its tests and a reproducible verification record.
5. Review [KNOWN_BUGS.md](KNOWN_BUGS.md) when diagnosing failures or modifying recovery/replay logic. Record newly confirmed bugs, affected versions, evidence, mitigations and verified resolutions.
6. Verify only the current ticket's acceptance criteria, run the relevant quality checks, update relevant docs, then **stop**. Summarize changed files, commands, evidence, remaining risks and the next *unblocked* ticket. Do not automatically execute the next ticket.

## Scope and guardrails
- RQ1 is **candidate coverage against human-confirmed gold**, not contract selection. RQ2 and RQ3 are outside the current implementation.
- Use original p01 (spec) and p02 (code) including native validation and repair; call existing gold scoring for offline evaluation. The original prompts, Z3 logic and repair ladder are behavioral reference points.
- Preserve the original 40 benchmark inputs and gold files. Freeze a group-aware 10-dev/30-test split before any experiment. Keep gold out of extraction prompts.
- Main sampling: 4 completed *attempt slots* per task/channel, `k=1,2,4`; baseline: 1 original attempt at T=0. The sampling temperature is nonzero **only on the initial generation**; native repairs remain at T=0.
- Keep independent successful samples, including identical text; never fill missing samples from cached replay responses. Distinguish provider faults from model/format failures and from inconclusive Z3 judgments.
- A live dev run is permitted only when the implementation ticket is explicitly started, after mock/offline tests and frozen run configuration. Held-out test requires **separate explicit authorization** after the dev gate. Do not run either as a side effect of documentation work.
- No wholesale refactoring, speculative features, wide formatting rewrites, or edits to old thesis branches. Keep API keys and raw sensitive provider credentials out of Git history.

## References and trigger pointers
- **Task scope or user-facing behavior:** [docs/rq1/SPEC.md](docs/rq1/SPEC.md)
- **Experimental sampling, oracle semantics, metrics, failure taxonomy or freeze procedure:** [docs/rq1/PROTOCOL.md](docs/rq1/PROTOCOL.md)
- **Starting, finishing or reviewing a single ticket:** [docs/rq1/tickets/README.md](docs/rq1/tickets/README.md) and its ticket file
- **Meaning of “attempt”, “candidate”, “gold-equivalent” or “unknown”:** [CONTEXT.md](CONTEXT.md)
- **Why an approach was chosen / how to change it:** [PROJECT_DECISIONS.md](PROJECT_DECISIONS.md)
- **Known failure, workaround or resolution:** [KNOWN_BUGS.md](KNOWN_BUGS.md)
- **Source project setup and pipeline:** [README.md](README.md), `pyproject.toml`

## Quality gate (when implementation is authorized)
Use the commands supported by the project, typically `poetry run ruff check .`, `poetry run mypy src`, and `poetry run pytest -q`; verify exact configuration before running. Tests of RQ1 behavior must work with **fake clients / recorded responses**, without contacting Groq. A clean check does not replace the ticket-specific tests or the documented Definition of Done.
