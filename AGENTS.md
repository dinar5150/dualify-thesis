# Dualify thesis — agent entry point

This branch is a **thesis research extension of original Dualify**. Base: [timur-harin/dualify](https://github.com/timur-harin/dualify) at `7ffd1ae37822096d5b7b573785ee46e877903185`. It studies *thesis RQ1*: whether four independently sampled, fully repaired formal contracts provide more **gold-oracle coverage** than one.

## Work order
1. Read [CONTEXT.md](CONTEXT.md) for the precise meaning of attempt, candidate, channel and oracle.
2. Read [docs/rq1/SPEC.md](docs/rq1/SPEC.md) **before changing experiment logic, benchmark handling or scoring**.
3. Read [PROJECT_DECISIONS.md](PROJECT_DECISIONS.md) before changing a frozen design choice; write the rationale for any approved amendment.
4. Choose the next unblocked ticket in [docs/rq1/tickets/README.md](docs/rq1/tickets/README.md). Complete its **Stopping criteria**, then stop work on that ticket.
5. If a defect appears, log it in [KNOWN_BUGS.md](KNOWN_BUGS.md) with reproduction, impact, fix and verification before closing the ticket.
6. Check [docs/rq1/STATUS.md](docs/rq1/STATUS.md) for the dev-only stop gate before initiating runs.

## Research guardrails
- Build from upstream source and the frozen 40-case benchmark; previous thesis branches are drafts and are not reference implementations.
- Preserve p01/p02 prompts, original validation + repair ladder, Z3 and gold references. New RQ1 code belongs in a separate research layer.
- Sampling: initial logical model call at one fixed nonzero temperature; subsequent repair calls at native T=0. Baseline: T=0 throughout.
- One candidate = one **full extraction attempt**. Keep invalid outputs and genuine duplicates. Infrastructure failures mark a slot incomplete, not a new free sample.
- Keep test IDs and test gold OUT of development tuning, model prompts and candidate export. The gold oracle is for offline assessment, not selection (RQ2).
- Analyze by spec and code channel separately, n=4 and k=1,2,4; handle solver UNKNOWN as uncertainty.
- **Stop after dev verification.** Do not run the 30-case held-out test without a separate explicit authorization.
- Never commit API keys or live raw transcripts containing secrets/personally sensitive data.

## Quick validation
See `pyproject.toml` for versions. Typical commands: `poetry run ruff check .`, `poetry run mypy src`, `poetry run pytest -q`. New RQ1 commands and exact prerequisites are documented in [docs/rq1/STATUS.md](docs/rq1/STATUS.md). A green check does not authorize starting test.
