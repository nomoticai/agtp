# Agent Transfer Protocol (AGTP)

**draft-hood-independent-agtp-01** | Informational | Independent Submission

> A dedicated application-layer protocol for autonomous AI agent traffic.

---

## What Is AGTP?

HTTP was designed for humans. AI agents are not humans.

Agent-generated traffic is autonomous, high-frequency, intent-driven,
and stateful across sequences of related requests. HTTP carries no
native semantics to distinguish an agent booking a flight from a
human clicking a link. It provides no protocol-level mechanism for
agent identity, authority scope, or attribution. And it cannot be
evolved to fix this — its method registry is frozen, its
backward-compatibility constraints are decades deep, and
infrastructure-level traffic differentiation is architecturally
impossible within HTTP's design.

AGTP is the dedicated transport layer that AI agents need. It sits
above TLS and below any agent messaging protocol (MCP, ACP, A2A),
providing:

- **Agent-native intent methods** — QUERY, SUMMARIZE, BOOK, SCHEDULE,
  LEARN, DELEGATE, COLLABORATE, CONFIRM, ESCALATE, NOTIFY — and a
  growing extended vocabulary organized by category
- **Protocol-level agent identity** — Agent-ID, Principal-ID, and
  Authority-Scope on every request, with an optional cryptographic
  certificate extension for verified identity
- **Governance primitives** — ESCALATE as a first-class method,
  authority scope enforcement, delegation chain tracking, and
  attribution records
- **Infrastructure observability** — agent traffic is distinguishable
  from human traffic at the routing layer without application-layer
  parsing

AGTP does not replace MCP, ACP, or A2A. Those are messaging protocols —
they define what agents say. AGTP defines how agent traffic moves.

---

## Status

| Item | Status |
|---|---|
| Internet-Draft | `draft-hood-independent-agtp-01` — active |
| IETF submission | Submitted |
| Working group | Independent submission (no WG assigned yet) |
| Reference implementation | Planned (Python / Go) — contributions welcome |
| Companion specs | `draft-hood-agtp-agent-cert-00` (pending), `draft-hood-agtp-standard-methods-00` (pending), `draft-hood-agtp-web3-bridge-00` (planned) |

This repository is the working home for the AGTP specification.
The I-D is under active development. Feedback, issues, and pull
requests are welcome.

---

## Repository Contents
```
draft-hood-independent-agtp-01.md    kramdown-rfc source (edit this)
draft-hood-independent-agtp-01.xml   RFC XML v3 (generated)
draft-hood-independent-agtp-01.txt   Plain-text I-D (IETF submission format)
draft-hood-independent-agtp-01.html  Rendered HTML (human-readable)
```

---

## The Protocol at a Glance

### Stack Position
```
+-----------------------------------------------------+
|            Agent Application Logic                  |
+-----------------------------------------------------+
|  Messaging Layer  (MCP / ACP / A2A)  [optional]     |
+-----------------------------------------------------+
|   AGTP - Agent Transfer Protocol      [this spec]    |
+-----------------------------------------------------+
|            TLS 1.3+                  [mandatory]    |
+-----------------------------------------------------+
|         TCP / QUIC / UDP                            |
+-----------------------------------------------------+
```

### Core Methods

| Method | Category | Intent |
|---|---|---|
| QUERY | Acquire | Semantic data retrieval |
| SUMMARIZE | Compute | Synthesize content |
| BOOK | Transact | Reserve a resource |
| SCHEDULE | Orchestrate | Plan future actions |
| LEARN | Compute | Update agent context |
| DELEGATE | Orchestrate | Transfer task to sub-agent |
| COLLABORATE | Orchestrate | Coordinate peer agents |
| CONFIRM | Transact | Attest to a prior action |
| ESCALATE | Orchestrate | Defer to human authority |
| NOTIFY | Communicate | Push information |

A three-tier method vocabulary extends beyond the core ten:
Tier 2 standard methods (FETCH, SEARCH, VALIDATE, TRANSFER,
MONITOR, RUN, and ~30 others) and Tier 3 industry profile methods
(healthcare, financial services, legal, infrastructure) are defined
in companion specifications.

### Three Problems AGTP Solves

**1. Undifferentiated agent traffic.** HTTP cannot distinguish agent
requests from human requests at the infrastructure layer. AGTP
provides a dedicated protocol environment — agent traffic is
identifiable at the routing layer without payload parsing.

**2. Semantic mismatch.** HTTP's GET/POST/PUT/DELETE vocabulary was
designed for resource manipulation, not purposeful action. AGTP's
intent-based methods express what an agent is trying to accomplish
at the protocol level.

**3. No protocol-level identity.** HTTP carries no native mechanism
for agent identity, authority scope, or attribution. AGTP embeds
Agent-ID, Principal-ID, and Authority-Scope on every request, with
an optional cryptographic Agent Certificate extension for verified
identity at the transport layer.

---

## New in v01: Agent Identity, URIs, and Registration

### Agent Birth Certificate

Every AGTP agent is issued an Agent Birth Certificate at registration
time — a cryptographically signed identity document that establishes
the agent's identity, owner, authorized scope, behavioral archetype,
and governance zone before the agent takes any action. The Birth
Certificate is the genesis record of the agent's existence. Its
`certificate_hash` field is the basis for the agent's canonical
256-bit Agent-ID. Authority is issued through the Birth Certificate;
it is never self-assumed.

Birth Certificate fields map directly to AGTP protocol headers on
every request: `agent_id` → `Agent-ID`; `owner` → `Principal-ID`;
`scope` → `Authority-Scope`.

### URI Structure

AGTP URIs are addresses, not filenames. The canonical forms are:

```
agtp://[256-bit-canonical-id]
agtp://[domain.tld]/agents/[agent-label]
agtp://agtp.[domain.tld]/agents/[agent-label]
```

Resolving an agent URI returns a signed **Agent Manifest Document**
(`application/agtp+json`) derived from the agent's package. The
manifest exposes identity, lifecycle state, trust tier, behavioral
scope, and birth certificate fields. It never exposes executable
content. File extensions (`.agent`, `.nomo`, `.agtp`) must not
appear in canonical URIs.

### Deployment Package Formats

| Format | Type | Description |
|---|---|---|
| `.agent` | Open (patent pending) | Manifest + integrity hash + behavioral trust score |
| `.nomo` | Governed (patent pending) | `.agent` + CA-signed cert chain + governance zone binding |
| `.agtp` | Protocol-native (this spec) | Wire-level manifest document returned by URI resolution |

The name `.nomo` derives from the Greek *nomos* (νόμος), meaning
law or governance — an agent operating under cryptographically
enforced behavioral constraints.

### Trust Tiers

| Tier | Verification | Package |
|---|---|---|
| 1 — Verified | DNS ownership challenge (RFC 8555) | `.nomo` required |
| 2 — Org-Asserted | None | `.agent` or `.nomo` |
| 3 — Experimental | None | Any; X- prefix required; not production-eligible |

---

## Intellectual Property

The **core AGTP specification** — all base methods, header fields,
status codes, and IANA registrations defined in this document — is
open and royalty-free.

Certain **extensions and mechanisms** referenced in the specification
may be subject to pending patent applications by the author,
specifically:

- The **Agent Certificate extension** (`draft-hood-agtp-agent-cert-00`)
- The **ACTIVATE method**
- The **Agent Birth Certificate mechanism**
- The **`.agent` file format specification**
- The **`.nomo` file format specification**

The licensor is prepared to grant a royalty-free license to
implementers for any patent claims covering these extensions,
consistent with the IETF's IPR framework under RFC 8179.

IPR disclosures are filed with the IETF Secretariat:
https://datatracker.ietf.org/ipr/

---

## Rebuilding the I-D

If you are contributing to the specification text, edit
`draft-hood-independent-agtp-01.md` and rebuild:
```bash
# Install toolchain (once)
pip install xml2rfc
gem install kramdown-rfc2629

# Rebuild
kramdown-rfc2629 draft-hood-independent-agtp-01.md > draft-hood-independent-agtp-01.xml
xml2rfc draft-hood-independent-agtp-01.xml --text
xml2rfc draft-hood-independent-agtp-01.xml --html
```

---

## Feedback and Contribution

This specification is in active development and pre-IETF working
group stage. All feedback is welcome:

- **Issues** — open a GitHub issue for questions, corrections, or
  gaps in the specification
- **Pull requests** — editorial improvements and clarifications to
  the spec text
- **Implementation reports** — if you are building an AGTP prototype,
  please share your findings via an issue; implementation reports
  will be incorporated into subsequent draft revisions
- **IETF discussion** — once submitted, discussion will move to the
  IETF DISPATCH mailing list (dispatch@ietf.org)

---

## Author

**Chris Hood** — AI Strategist, Author, Founder of Nomotic AI

- [chrishood.com](https://chrishood.com)
- [nomotic.ai](https://nomotic.ai)
- [@chrishood](https://linkedin.com/in/chrishood)

---

## License

The specification text in this repository is licensed under
[Creative Commons Attribution 4.0 International (CC-BY 4.0)](https://creativecommons.org/licenses/by/4.0/).

You are free to share and adapt the material for any purpose,
provided appropriate credit is given, a link to the license is
provided, and any changes are indicated.

This license applies to the **specification text**. It does not
grant rights to any pending patent claims on extensions described
in the specification. See the Intellectual Property section above.