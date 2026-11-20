# Agent documentation index

This folder contains instructions and long-lived research context used by AI coding agents. The root [AGENTS.md](../../AGENTS.md) stays short so editor agents discover it automatically and follow these pointers.

| Document | Read when |
| --- | --- |
| [AGENT_GUIDE.md](AGENT_GUIDE.md) | Starting or reviewing any RQ1 implementation ticket; follow the one-ticket-at-a-time workflow and stopping rules. |
| [CONTEXT.md](CONTEXT.md) | Interpreting terms such as candidate, attempt, gold equivalence and unknown. |
| [PROJECT_DECISIONS.md](PROJECT_DECISIONS.md) | Considering architecture or methodology changes; understand what has been approved and why. |
| [KNOWN_DUALIFY_LIMITATIONS.md](KNOWN_DUALIFY_LIMITATIONS.md) | Diagnosing **original Dualify/Z3** behavior or discussing limitations of the paper; preserve the original methodology. |
| [KNOWN_BUGS.md](KNOWN_BUGS.md) | Diagnosing and recording defects/risks specific to **our RQ1 extension**, including replay and provider recovery. |

The research design and implementation tasks are separate: [RQ1 specification](../rq1/SPEC.md), [evaluation protocol](../rq1/PROTOCOL.md), [tickets](../rq1/tickets/README.md).

**Ownership rule:** original-method limitations live only in KNOWN_DUALIFY_LIMITATIONS; RQ1 implementation issues live in KNOWN_BUGS. Cross-reference rather than duplicating investigations.
