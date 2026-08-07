# Presence withdrawal convergence

Without retained delete state, a peer that misses `WITHDRAW` can later send
back its old presence record. The agent then appears to come back by itself.

This implementation leaves a tombstone after `WITHDRAW` and exchanges it
through the existing `REPLICATE` anti-entropy path. Coordinator signing signs
hosted withdrawals. Gossip signature verification verifies tombstones like
live records.

## Rules

- Signed tombstones and live records are ordered by their authenticated epoch.
  A withdrawal wins a tie.
- For signed state, the key must remain the same across announce, withdraw,
  and a later re-announce.
- `DISCOVER /population` does not return a record suppressed by a retained
  valid tombstone.
- The receiving coordinator chooses the base retention period. A withdrawal
  carries no retention request.
- The reference default is 24 hours, measured from the receiver's first merge.
  `--presence-tombstone-retention-seconds 0` disables time-based tombstone GC.
- Expired live records and invalid epoch or TTL values are not merged.

`REPLICATE` adds optional `tombstones` and `tombstone_digest` fields. Older
peers ignore them, so a mixed-version deployment does not provide deletion
convergence.

## Boundary

The finite guarantee applies only when disconnected peers rejoin and finish
anti-entropy within the receiver's retention window. This is the same boundary
that creates "zombie" data when a Cassandra replica stays away past its grace
period. A peer absent longer than the configured window needs re-synchronizing
from trusted current state. For non-expiring presence records
(`ttl_seconds=0`), operators need to disable time-based tombstone GC and
persist that state, or move to finite, periodically refreshed leases.

The reference store is in memory, so tombstones do not yet survive a
coordinator restart.

Foreign state whose Genesis cannot be resolved keeps the existing
trust-on-first-use limitation.

The design follows the same two ideas used elsewhere: deletion markers with an
operator-controlled grace period in
[Cassandra](https://cassandra.apache.org/doc/latest/cassandra/managing/operating/compaction/tombstones.html)
and finite, periodically republished provider records in
[IPFS Kademlia](https://specs.ipfs.tech/routing/kad-dht/).
