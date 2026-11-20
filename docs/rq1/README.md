# Thesis RQ1 — planning hub

**Stage:** approved design; implementation **not started**. This documentation-only branch is based on original `timur-harin/dualify` commit `7ffd1ae37822096d5b7b573785ee46e877903185`, rather than any earlier fork branch.

## Read in this order
1. [SPEC.md](SPEC.md) — problem, solution, user stories, scope and testing decisions (**what** must be true).
2. [PROTOCOL.md](PROTOCOL.md) — dataset, sampling, retry and oracle rules, frozen reporting requirements (**how** the study is measured).
3. [tickets/README.md](tickets/README.md) — dependency graph and six independently verifiable tasks (**where** to work next).
4. [../../PROJECT_DECISIONS.md](../agent/PROJECT_DECISIONS.md) — user-approved trade-offs and pending configuration choices (**why**).
5. [../../CONTEXT.md](../agent/CONTEXT.md) — precise research terminology.
6. [../agent/KNOWN_DUALIFY_LIMITATIONS.md](../agent/KNOWN_DUALIFY_LIMITATIONS.md) — established limitations and future reported bugs of original Dualify; frozen Z3 behavior.
8. [../../KNOWN_BUGS.md](../agent/KNOWN_BUGS.md) — confirmed technical hazards and outstanding issues.
7. [../../AGENTS.md](../agent/AGENT_GUIDE.md) — agent workflow and stopping rules.

## Stage gates

**Documents (this branch)** → **offline implementation and tests (Tickets 01–04)** → **a single authorized dev campaign and independent review (Ticket 05)** → **STOP / freeze and request a separate test authorization** → **held-out 30-case evaluation (Ticket 06)**.

Current requested stop: deliver and audit Markdown specification/tickets; **no source code changes and no Groq calls**.

## Source of truth
The upstream README and Python source describe existing Dualify behavior. The spec/protocol describe the approved **new thesis experiment**. Do not treat original paper RQ1–RQ7 numbering as identical to the **thesis** RQ1–RQ3.
