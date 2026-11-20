# RQ1 execution state

**Stage:** Implementation authorized; dev-only scope. **Upstream baseline:** `7ffd1ae37822096d5b7b573785ee46e877903185`. **Branch:** `rq1-sampling-from-upstream-20261120`.

## Gates
- [ ] Ticket 01 frozen split/audit
- [ ] Ticket 02 candidate adapter parity and failure classification
- [ ] Ticket 03 four-slot recording/resume/strict replay
- [ ] Ticket 04 offline gold pass@k/uncertainty/latency analysis
- [ ] Ticket 05 all tests, **live dev only**, independent review
- [ ] **READY FOR HELD-OUT TEST** — stop after passing all above
- [ ] Ticket 06 held-out test — **BLOCKED pending new explicit approval**

## Environment
- Groq model ID, temperature and actual rate limits: **not yet verified**.
- API key: via local environment variable `GROQ_API_KEY`; never commit or paste into logs.
- No live dev campaign can be declared complete without real account access, complete slot artifacts and successful strict replay.
- Record any deviations in [PROJECT_DECISIONS.md](../../PROJECT_DECISIONS.md) and defects in [KNOWN_BUGS.md](../../KNOWN_BUGS.md).
