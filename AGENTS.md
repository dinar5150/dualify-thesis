# Agent entry point

This repository studies **thesis RQ1** on the original Dualify codebase. Detailed agent instructions are maintained under [docs/agent/](docs/agent/README.md).

1. **Read [docs/agent/AGENT_GUIDE.md](docs/agent/AGENT_GUIDE.md)** before starting an RQ1 ticket. It contains the workflow, approval gates and stopping rules.
2. **Read [docs/agent/KNOWN_DUALIFY_LIMITATIONS.md](docs/agent/KNOWN_DUALIFY_LIMITATIONS.md)** before investigating the original Dualify algorithm or Z3 behavior. Preserve the upstream Z3 oracle, solver timeout, fragment semantics and native extraction/repair behavior; document known defects instead of fixing them as part of RQ1.
3. **Read [docs/rq1/SPEC.md](docs/rq1/SPEC.md)** and [docs/rq1/PROTOCOL.md](docs/rq1/PROTOCOL.md) for the approved study, then choose **one unblocked ticket** from [docs/rq1/tickets/README.md](docs/rq1/tickets/README.md). Stop at its explicit completion criterion.

**Current authorization:** documentation maintenance only. No Python implementation, Groq experiments or held-out test run is authorized by this change.
