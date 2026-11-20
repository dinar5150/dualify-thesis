# 03 — Make a four-candidate pool resumable and strictly replayable

**Status:** ready-for-agent (NOT STARTED)  
**Blocked by:** [02 — Native attempt and telemetry](02-native-attempt-and-telemetry.md).  
**Deliverable:** An end-to-end **offline** example that produces a baseline and four individually identifiable treatment attempts per channel for one case, persists them, resumes safely and verifies them by replay.

## Problem
Repeating the same prompt does not establish independent sampling unless every output came from a separate live attempt slot. The original transcript's prompt-matching replay can reuse a previously recorded response if the prompt occurs too many times. Crashes and provider outages can also cause missing or duplicated slots. Without a robust ledger, later pass@k is untrustworthy.

## Known facts
- Original `RecordingLLMClient`, `ReplayLLMClient` and `ResumingLLMClient` implement prompt-hash transcription and replay.
- Original `ReplayLLMClient(match_by_prompt=True)` may serve the last known response again after recorded responses to the same prompt are exhausted; this is **not** an additional sample.
- Upstream strict sequential replay checks ordered prompt hashes; original extractors may swallow replay exceptions, so strictness needs an outer completion/exhaustion check.
- The approved experiment has exactly four treatment candidate **slots** per case/channel, plus one baseline slot; duplicate formulas are legitimate.
- Infrastructure failure recovery is allowed only for the **same** incomplete slot; completed-but-incorrect slots cannot be replaced.

## Constraints
- Assign stable IDs such as (task, channel, arm, sample-index), with a separate unique logical-call order within every slot.
- Preserve raw prompts/temperatures and final native extraction traces; record sufficient data for offline verification without API credentials.
- Use existing transcript semantics where safe; enforce strict ordered replay, prompt/hash consistency, recorded call cardinality and exhaustion **above** the extraction layer.
- Never mint new samples from replayed or cached output. Preserve formula duplicates as distinct **only if** recorded from separate actual attempts.
- Use append-only data or atomic slots; a crash must not silently duplicate a completed slot or truncate and “complete” one.
- Mark missing/exhausted infrastructure slots as incomplete. Preserve successful prefixes and retry history; do not shorten n for analysis.
- Keep this ticket runnable with fake client responses and no real Groq calls.

## Hypotheses
- **Engineering hypothesis:** a candidate ledger plus outer replay verifier can reuse original transcript functionality and guarantee exactly-once *slot bookkeeping* across interruption/resumption without promising deterministic live sampling.

## Expected outcome
- One reproducible fixture: one benchmark task, both channels, one baseline + four treatment slots per channel, unique slot IDs and cross-linked extraction/transcript records.
- A successful offline replay that regenerates the same final candidate records and verifies all recorded calls were consumed.
- Intentional corruption tests: missing LLM record, extra record, wrong prompt hash, reused last response, duplicate slot ID, interrupted slot and resumed same-slot completion.

## Acceptance criteria
- [ ] Four *completed distinct IDs* per case/channel are required and present, with one separate baseline; duplicates in candidate **text** do not change the count.
- [ ] Every completed slot refers to real ordered recorded model responses (or fake responses in tests) and exactly one final native extractor result.
- [ ] Strict replay validates ordered prompts, temperatures, call counts, response identity and full exhaustion; fail closed on all corruption fixtures.
- [ ] A replay mismatch swallowed by native extraction still makes outer verification fail, not silently yield a valid-looking degraded candidate.
- [ ] Replay and resumption never call the network during offline verification.
- [ ] A transient interrupted slot resumes in place and preserves previously completed slots; repeated resume is idempotent under tested conditions.
- [ ] An invalid/degraded but completed native model output is kept, while a true unresolved infrastructure slot blocks the campaign.
- [ ] Existing original transcript tests still pass.

## Stopping criteria
**STOP when:** the one-case two-channel fixture proves complete n=4 pools, resumability and strict zero-network replay, and all corruption fixtures deterministically fail. If exact identity cannot be established from the available transcript, report `BLOCKED`; do not silently weaken verification. Do not generate real candidates or add gold scoring beyond a placeholder hook.

## Out of scope
Gold oracle pass@k, statistical confidence intervals, real Groq campaigns or general-purpose transcript refactoring.
