# Known bugs, verified hazards and resolutions

This is the active defect register. A **verified hazard** is a behavior observed in upstream source that could invalidate RQ1 if used incorrectly; it is not necessarily a defect in the original Dualify product. An **unverified risk** is not labeled a confirmed bug. No RQ1 implementation fixes have been made as part of the documentation phase.

| ID | State | Category | Location / evidence | Impact on RQ1 | Mitigation / resolution |
| --- | --- | --- | --- | --- | --- |
| RQ1-001 | **Verified hazard; open** | Replay | Upstream `ReplayLLMClient(match_by_prompt=True)` reuses the last recorded answer if calls with an identical prompt exceed available records. | Can silently produce apparent extra independent candidates from one recorded response. | Require strict sequential replay, expected call/slot counts, explicit candidate IDs and fail-closed verification in Ticket 03. **Not fixed yet.** |
| RQ1-002 | **Verified hazard; open** | Failure attribution | Upstream p01/p02 catch broad exceptions and may yield a degraded extraction. | A failed Groq call might look like a valid completed negative candidate; a retry could wrongly replace a genuine model failure. | Log provider events at the client boundary and classify cause before finalizing a slot; test swallowed-failure cases in Ticket 02/03. **Not fixed yet.** |
| RQ1-003 | **Observed limitation; open** | Measurement | A logical `generate_json` call may hide transport retries/fallback endpoints. Original extraction interface does not expose complete physical HTTP timings. | Logical call count and extractor elapsed time cannot be presented as exact HTTP call count or pure model inference latency. | Report actual available metrics and coverage; optionally instrument transport narrowly with verification. **Not fixed yet.** |
| RQ1-004 | **Audit pending** | Benchmark leakage | Some upstream inputs include embedded formal annotations; several tasks are near-duplicates or have generic informal specs. | Inflated apparent extraction success or dev/test contamination. | Ticket 01 records complete case-level audit and group-aware split; preserve inputs and disclose the limitations. **Not verified as test leakage.** |
| RQ1-005 | **Potential provider hazard; not reproduced here** | API output format | Providers may surface generated JSON validation failures via HTTP error responses. | Treating all 4xx responses as infrastructure errors can bias success by free retries. | Distinguish error-body causes, stop on config/auth failures, count model-format failures under native extraction policy. Validate with offline fakes in Ticket 02. |

## How to update this register

When a bug is reproduced, record **date**, **commit**, **minimal reproduction**, **expected vs actual behavior**, **severity**, **affected ticket**, **fix commit**, **regression test** and **verification outcome**. Change state only when evidence supports it:

`observed / reproduced → investigating → fixed-in-branch → verified-resolved`, or `non-bug / accepted limitation` with rationale.

### Resolved incidents
None documented on the clean upstream-based documentation branch as of 2026-11-20. Do not import old fork branch issues as if they were current defects.
