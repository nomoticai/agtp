---
title: "AGTP Transparency Log Protocol"
abbrev: "AGTP-LOG"
docname: draft-hood-agtp-log-00
category: info
submissiontype: independent
ipr: trust200902
area: "Applications and Real-Time"
workgroup: "Independent Submission"
keyword:
  - AI agents
  - transparency log
  - SCITT
  - agent identity
  - governance

stand_alone: yes
pi:
  toc: yes
  sortrefs: yes
  symrefs: yes

author:
  - fullname: Chris Hood
    organization: Nomotic, Inc.
    email: chris@nomotic.ai
    uri: https://nomotic.ai

normative:
  RFC2119:
  RFC8174:
  RFC9162:
  RFC9943:
  AGTP:
    title: "Agent Transfer Protocol (AGTP)"
    author:
      fullname: Chris Hood
    seriesinfo:
      Internet-Draft: draft-hood-independent-agtp-05
    date: 2026

informative:
  AGTP-CERT:
    title: "AGTP Agent Certificate Extension"
    author:
      fullname: Chris Hood
    seriesinfo:
      Internet-Draft: draft-hood-agtp-agent-cert-00
    date: 2026

--- abstract

This document specifies the AGTP Transparency Log (AGTP-LOG): the
append-only log protocol that underpins the `log-anchored` Trust Tier 1
verification path defined in {{AGTP}}. AGTP-LOG aligns with RFC 9162
(Certificate Transparency 2.0) as the verifiable data structure and
issues COSE_Sign1 receipts per RFC 9943 (SCITT) for cross-ecosystem
interoperability. This document also introduces the AGTP Agent Identity
Taxonomy (Agent Genesis, Canonical Agent-ID, Agent Certificate),
clarifying the terminology previously expressed as "Birth Certificate"
across the AGTP draft family. The taxonomy will be adopted in the next
revisions of {{AGTP}} and {{AGTP-CERT}}. This is an early working
draft; scope, federation model, and receipt schema are placeholders
pending further work.

--- middle

# Introduction

AGTP v05 recognizes `log-anchored` as one of three equivalent Trust
Tier 1 verification paths. This document specifies the log protocol
that path depends on. The current inline AGTP-CTL section in {{AGTP-CERT}}
is superseded by this document; AGTP-CERT's next revision will reference
AGTP-LOG normatively rather than define its own log.

# Terminology

## AGTP Agent Identity Taxonomy

AGTP identity is composed of three distinct elements. This taxonomy is
introduced in AGTP-LOG because the log protocol depends on precise
distinctions between them. It will be adopted across the AGTP draft
family in subsequent revisions, replacing the "Birth Certificate"
terminology in {{AGTP}} and {{AGTP-CERT}}.

Agent Genesis:
: The permanent, signed governance-layer document produced at ACTIVATE
  time that establishes an agent's identity. The Agent Genesis is the
  origin record from which all other identity artifacts derive. It is
  issued by the governance platform, signed with the governance
  platform's key, and archived on revocation. An Agent Genesis is
  never reissued; the identity it establishes is permanent for the
  life of the agent. Supersedes the "Birth Certificate" terminology
  in prior AGTP drafts.

Canonical Agent-ID:
: A 256-bit cryptographic hash of the Agent Genesis, used as the
  agent's identifier in all AGTP protocol operations. The Canonical
  Agent-ID is the value carried in the `Agent-ID` header on every
  request, the key in the registry, and the subject of transparency
  log entries. The Canonical Agent-ID is derived from the Agent
  Genesis; it is not an independent value.

Agent Certificate:
: An optional X.509 v3 credential defined in {{AGTP-CERT}} that binds
  the Canonical Agent-ID to TLS mutual authentication for transport-
  layer verification and O(1) scope enforcement at Scope-Enforcement
  Points. Agent Certificates are renewable and revocable, with a
  recommended 90-day validity period. The Agent Certificate is a
  derived credential, not an identity substrate; it references the
  Agent Genesis via the `activation-certificate-id` extension.

The relationship among these three elements:

~~~~
ACTIVATE (method call)
   │
   ├──produces──►  Agent Genesis (signed JSON document)
   │                    │
   │                    └──hashed to produce──►  Canonical Agent-ID
   │
   └──optionally, for Level 3 deployments──►  Agent Certificate (X.509)
                                                  │
                                                  └──references──►  Agent Genesis
~~~~

> Editorial note: Once this taxonomy is adopted in the next revisions
> of {{AGTP}} and {{AGTP-CERT}}, the "Birth Certificate" term will be
> retained only in non-normative contexts (blog posts, marketing
> materials) where its metaphorical weight serves audience
> understanding. Normative specification language will use "Agent
> Genesis" exclusively.

## Log-Specific Terminology

- TBD: log, log operator, witness, monitor, receipt, inclusion proof,
  consistency proof. Defer to {{RFC9162}} and {{RFC9943}} where possible.

# Log Scope

Events subject to logging (working list, to be narrowed):

- Agent Genesis issuance
- Agent Genesis revocation
- Lifecycle transitions (suspend, reinstate, deprecate)
- Agent Certificate issuance and revocation (from {{AGTP-CERT}})

# Log Architecture

Working assumption: per-governance-platform logs with optional
cross-witnessing. Matches SCITT convention and typical issuer-local
deployment. Alternative models (global AGTP log, federated logs) to
be evaluated.

# Entry Format

SCITT-aligned statements per {{RFC9943}}. Each entry carries:

- Subject: Canonical Agent-ID
- Payload: Agent Genesis or lifecycle event record
- Issuer: governance platform
- Signature: governance platform key

Exact CBOR schema TBD.

# Receipt Format

COSE_Sign1 receipts per {{RFC9943}} with `RFC9162_SHA256` as the
verifiable data structure type. Content type
`application/scitt-receipt+cose`. Matches deployed SCITT tooling.

# Log Protocol

Working list of operations, details TBD:

- Submit statement
- Retrieve receipt
- Retrieve inclusion proof
- Retrieve consistency proof

# Discovery

How a verifier holding a Canonical Agent-ID locates the log that
contains the inclusion proof. Likely mechanism: a `log_uri` field in
the Agent Genesis and Agent Manifest Document. Alternatives under
consideration.

# Integration with AGTP

The `log_inclusion_proof` field in the Agent Genesis ({{AGTP}}
Section 5.6) references the inclusion proof produced by this log. A
verifier retrieves the proof, validates it against the log's signed
tree head, and confirms the Agent Genesis is committed to the log.

# Security Considerations

TBD. Covers log operator compromise, split-view attacks, witness
collusion, private key handling, and log-anchored Tier 1 threat model
per {{AGTP}} Section 7.

# IANA Considerations

Content types, well-known URIs, and OIDs to be specified.

--- back

# Open Questions

- Should Agent Certificate issuances be logged here or remain in
  AGTP-CERT's scope?
- Federation model: per-platform logs with cross-witnessing vs. other
  patterns?
- Discovery mechanism: Agent Genesis field vs. well-known
  endpoint vs. both?
- Should AGTP-LOG define witness and monitor roles, or defer to SCITT?

# Contributors

Feedback from Scott Courtney (GoDaddy / ANS) on SCITT alignment and
production deployment considerations informs this draft.
