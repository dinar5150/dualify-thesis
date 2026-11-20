# Known bugs and limitations

Maintain one item per defect. Use: **ID / Status / Impact / Reproduction / Resolution / Verification**. `OPEN`, `BLOCKED`, `RESOLVED`, and `LIMITATION` are distinct statuses. Move resolved issues to the resolved section; retain how they were verified.

## Open / inherited risks

### KB-001 — Prompt-hash replay may invent repeated samples
**Status:** OPEN (upstream behavior; must avoid in RQ1).  
**Impact:** `ReplayLLMClient(match_by_prompt=True)` reuses the final stored response after exhausting a prompt's records; invalid for independently sampled pass@k.  
**Reproduction:** Call the same prompt more times than stored with match-by-prompt enabled.  
**Resolution plan:** Strict per-slot sequential replay, temperature/hash matching, exact count/exhaustion checks. Keep native helper untouched.  
**Verification:** Fake recorded transcripts with repeated prompts must fail rather than fabricate new slots.

### KB-002 — Provider errors can be returned as degraded extraction
**Status:** OPEN (upstream behavior; must classify in RQ1).  
**Impact:** Original p01/p02 may swallow network/client exceptions and return a degraded placeholder; without instrumentation this looks like an ordinary wrong candidate.  
**Reproduction:** Fake `generate_json` raises an exhausted 429/timeout inside original extraction.  
**Resolution plan:** RQ1 client wrapper records failure provenance and marks the slot incomplete; model-produced invalid JSON is handled separately.  
**Verification:** Deterministic error and resume tests.

### KB-003 — Client timeout and Groq quota obscure latency comparisons
**Status:** LIMITATION (provider-dependent).  
**Impact:** Extractor elapsed time includes HTTP backoff, provider queuing and retries; native interface does not expose exact server inference latency or physical retry counts.  
**Reproduction:** Rate-limit responses increase overall runtime without changing model work.  
**Resolution plan:** Measure elapsed full-attempt time and logical call counts; label unavailable metrics `not_measured`, and document account limits.  
**Verification:** Report schema and sample output reviewed against actual instrumentation.

### KB-004 — Original benchmark can expose formal annotations inside code input
**Status:** LIMITATION (to be quantified by Ticket 01).  
**Impact:** Code-channel inputs may contain `pre:`/`post:` docstrings, and some informal specs are generic.  
**Resolution plan:** Audit and report only; no input rewriting or sample exclusion.  
**Verification:** Audit inventories all 40 inputs and lists affected IDs.

## Resolved

None yet. A proposed workaround is not a resolved bug.
