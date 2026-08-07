# Presence withdrawal convergence

AGTP Presence represents a graceful `WITHDRAW` as a retained tombstone.
The tombstone participates in the same `REPLICATE` anti-entropy exchange as
live presence records, so a stale peer cannot restore a withdrawn record when
it reconnects after a temporary partition.

## Wire shape

`REPLICATE` keeps the existing `records` and `digest` fields and adds two
optional fields:

```json
{
  "tombstones": [
    {
      "agent_id": "...",
      "withdrawn_at": "2026-08-08T00:00:00Z",
      "withdrawn_at_epoch": 1786147200.0,
      "retention_seconds": 86400,
      "signature": {
        "alg": "EdDSA",
        "payload_version": 1,
        "public_key": "...",
        "value": "..."
      }
    }
  ],
  "tombstone_digest": {"...": 1786147200.0}
}
```

Older peers can ignore these fields. Tombstone-aware peers merge tombstones
before live records and return missing tombstones in the `REPLICATE` response.

## Conflict and authorization rules

- The newest authenticated state wins by announce/withdraw epoch.
- A tombstone for an existing signed record must use the same Ed25519 key.
- A newer record may supersede a signed tombstone only when it uses the same
  key and its version 2 signature covers `announced_at_epoch` and
  `ttl_seconds`.
- Version 1 record signatures remain verifiable for compatibility, but their
  unsigned conflict epoch cannot supersede a signed tombstone.
- When signature verification is enabled for gossip, tombstone verification
  is fail-closed as well.

For hosted records, the signing coordinator signs the tombstone. A foreign
agent may submit its own signed tombstone in the `WITHDRAW` body.

## Retention boundary

The default tombstone retention is 24 hours. Deletion convergence is therefore
guaranteed for peers that reconnect and complete anti-entropy within that
window. A peer returning after the tombstone has been garbage-collected may
still present stale state until the old record's TTL expires. Set
`retention_seconds` to `0` only when indefinite retention and its memory cost
are acceptable.

Cryptographic signature verification proves possession of the embedded key.
For an Agent-ID whose Genesis is not resolvable, the existing foreign-presence
trust-on-first-use limitation still applies.
