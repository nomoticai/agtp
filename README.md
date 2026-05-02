# AGTP — Agent Transfer Protocol

A dedicated application-layer protocol for AI agent traffic.
Specification, Internet-Draft, and reference implementation.

- **IETF submission:** `draft-hood-independent-agtp-06`
- **IANA-registered ports:** 4480/TCP (`agtp`) and 4480/UDP (`agtp-quic`)
- **Reference implementation:** `v1/` (this repository)
- **First registered agent:** Lauren —
  `agtp://d8dc6f0df55d66c7b30100db3cffbe383c5f814e6e58a08521fb7636c3bcc230`

## Repository layout

```
agtp/
├── ietf/              IETF Internet-Draft sources (markdown)
├── v1/                Reference implementation (Python)
│   ├── agent_id.py
│   ├── agent_document.py
│   ├── wire_v2.py
│   ├── renderer.py
│   ├── server/
│   │   ├── agent_server.py
│   │   └── agents/
│   │       └── lauren.agent.json
│   ├── registry/
│   │   └── registry_server.py
│   ├── client/
│   │   └── agtp.py
│   └── run_demo.sh
├── docs/
│   └── DEPLOY.md       Deployment guide for fresh VPS
└── scripts/
    └── agtp-deploy.sh  VPS deploy automation
```

The protocol specification and the reference implementation live in
the same repository because they evolve together. Future revisions
land in `v2/`, `v3/` etc. — earlier `vN/` directories are kept for
historical reference.

## What v1 demonstrates

- Canonical AGTP URIs (`agtp://{agent-id}`) resolve end-to-end via
  registry lookup
- Form 1a (`agtp://{agent-id}@{host}`) bypasses the registry for direct
  resolution before federated infrastructure exists
- Agent Identity Documents in `application/vnd.agtp.identity+json` carry
  the eleven-field v1 identity schema
- Content negotiation produces JSON, YAML, or rendered HTML from the
  same URI based on the client's `Accept` header
- DESCRIBE method serves Agent Identity Documents over AGTP wire format
  on port 4480

## Quick start (local)

```bash
cd v1
./run_demo.sh
```

This starts a registry on `127.0.0.1:8080`, registers Lauren, starts
the agent server on `127.0.0.1:4480`, then runs four scenarios:

1. `agtp://{lauren-id}` → JSON
2. `agtp://{lauren-id}` → YAML
3. `agtp://{lauren-id}` → rendered HTML identity card
4. `agtp://{lauren-id}@127.0.0.1:4480` → direct host form

## Public deployment

See [`docs/DEPLOY.md`](docs/DEPLOY.md) for a step-by-step walkthrough
from fresh Ubuntu 24.04 LTS VPS to AGTP running publicly under your
own domain.

The reference public deployment is at:

- **Registry:** `https://registry.agtp.io`
- **Agents:** `agents.agtp.io:4480`

## Lauren's identity

```
agtp_version:    1.0
agent_id:        d8dc6f0df55d66c7b30100db3cffbe383c5f814e6e58a08521fb7636c3bcc230
name:            Lauren
principal:       Chris Hood
description:     The first AGTP-identified agent.
status:          active
capabilities:    [DESCRIBE]
scopes_accepted: [identity:read, capability:read]
issuer:          agtp.io
```

## What's not in v1

Deliberate scope cuts, listed for future revisions:

- **Cryptographic signatures.** Agent Documents are unsigned in v1;
  v2 wires in Birth Certificate signing.
- **Trust scores.** Mentioned in the spec but not yet computed.
- **Public registration UI** at `https://register.agtp.io`.
- **AGTP-CERT integration** at `https://ca.agtp.io`.
- **Methods beyond DESCRIBE** — QUERY, BOOK, DELEGATE, etc.
- **`.well-known/agtp` bootstrap** for non-AGTP-native domains.
- **Federated registries** — v1 hardcodes one registry.

## License and IPR

The core protocol specification is open and royalty-free. See
[`ietf/`](ietf/) for the Internet-Drafts and their IPR sections.

## Contributing

The protocol is in active development under Independent Submission to
the IETF. Issues and discussion welcome. Implementation reports —
"I tried to implement v06 and ran into..." — are especially valued.

## Contact

Chris Hood — chris@nomotic.ai
