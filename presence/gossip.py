"""
Gossip anti-entropy between full-node coordinators (PDD §6.1 "Gossip").

Two coordinators reconcile their presence views so an agent announced at
one becomes discoverable at the other, while a graceful WITHDRAW remains
deleted after a temporary partition. The exchange is a single
``REPLICATE`` round-trip carrying live records, retained tombstones, and
separate digests; the receiver merges and returns only the missing delta:

    A -> B  {records: [...], tombstones: [...], digest: {...},
             tombstone_digest: {...}}
    B       merges tombstones before records (newest signed state wins),
            replies with the live-record and tombstone deltas
    A       merges B's reply

Both sides converge on the union in one call. The request-side digest is
where the bandwidth optimization lives (send hashes, pull full records on
delta); M2 pushes full records because scope populations are small, and
notes the digest-diff refinement for later.

Trust: callers can require Ed25519 verification for both records and
tombstones. Signed state also enforces key continuity across a withdrawal
and later re-announcement. Without verification, the existing cooperative
development mode accepts unsigned state. Visibility is NOT applied during
gossip: records propagate with their posture intact and are filtered
per-requester at query time.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from client.core_client import send_method
from core import wire
from presence.records import PresenceRecord, PresenceTombstone


GOSSIP_VERB = "REPLICATE"


def build_replicate_request(store) -> Dict[str, Any]:
    """Full live/tombstone push sets plus their compact digests."""
    return {
        "records": [r.to_gossip_dict() for r in store.all_records()],
        "tombstones": [t.to_gossip_dict() for t in store.all_tombstones()],
        "digest": store.digest(),
        "tombstone_digest": store.tombstone_digest(),
    }


def apply_replicate(
    store,
    body: Dict[str, Any],
    *,
    verify=None,
    verify_tombstone=None,
) -> Dict[str, Any]:
    """
    Receiver side: merge tombstones before live records, then compute the
    two deltas the sender needs. Returns the response body.

    ``verify`` is an optional ``record -> bool`` predicate; records that
    fail it (e.g. an unsigned or tampered record when signature
    verification is required) are dropped rather than merged, so a peer
    cannot inject a forged or mutated announcement. When record verification
    is enabled, ``verify_tombstone`` must also be supplied; otherwise
    tombstones are rejected closed.
    """
    tombstones_merged = 0
    tombstones_rejected = 0
    for raw in body.get("tombstones") or []:
        try:
            tombstone = PresenceTombstone.from_gossip_dict(raw)
        except (KeyError, TypeError, ValueError):
            continue
        if verify is not None and verify_tombstone is None:
            tombstones_rejected += 1
            continue
        if verify_tombstone is not None and not verify_tombstone(tombstone):
            tombstones_rejected += 1
            continue
        if store.merge_tombstone(tombstone):
            tombstones_merged += 1

    merged = 0
    rejected = 0
    for raw in body.get("records") or []:
        try:
            record = PresenceRecord.from_gossip_dict(raw)
        except (KeyError, TypeError, ValueError):
            continue  # skip malformed entries rather than failing the round
        if verify is not None and not verify(record):
            rejected += 1
            continue
        if store.merge_record(record):
            merged += 1

    remote_digest = body.get("digest") or {}
    if not isinstance(remote_digest, dict):
        remote_digest = {}
    remote_tombstone_digest = body.get("tombstone_digest") or {}
    if not isinstance(remote_tombstone_digest, dict):
        remote_tombstone_digest = {}
    delta = store.records_peer_needs(
        remote_digest,
        remote_tombstone_digest=remote_tombstone_digest,
    )
    tombstone_delta = store.tombstones_peer_needs(remote_tombstone_digest)
    return {
        "merged": merged,
        "rejected": rejected,
        "tombstones_merged": tombstones_merged,
        "tombstones_rejected": tombstones_rejected,
        "records": [r.to_gossip_dict() for r in delta],
        "tombstones": [t.to_gossip_dict() for t in tombstone_delta],
    }


def gossip_once(
    store,
    host: str,
    port: int,
    *,
    use_tls: bool = True,
    insecure_skip_verify: bool = False,
    verify=None,
    verify_tombstone=None,
) -> Tuple[int, int]:
    """
    Run one anti-entropy round against a single peer. Returns
    ``(pushed, pulled)`` — presence objects sent and merged from the reply.
    Network/parse errors are swallowed (a peer being down must not break
    the local coordinator); the round simply reconciles nothing.

    ``verify`` and ``verify_tombstone`` drop unverifiable reply objects.
    """
    request_body = build_replicate_request(store)
    pushed = len(request_body["records"]) + len(request_body["tombstones"])
    body_bytes = json.dumps(request_body).encode("utf-8")
    try:
        resp = send_method(
            None,  # server-level: the peer's presence hook owns REPLICATE
            host,
            port,
            GOSSIP_VERB,
            body=body_bytes,
            body_content_type="application/json",
            use_tls=use_tls,
            insecure_skip_verify=insecure_skip_verify,
        )
    except (OSError, wire.WireFormatError):
        return (0, 0)

    if resp.status_code != 200 or not resp.body_bytes:
        return (pushed, 0)
    try:
        reply = json.loads(resp.body_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return (pushed, 0)

    pulled = 0
    for raw in reply.get("tombstones") or []:
        try:
            tombstone = PresenceTombstone.from_gossip_dict(raw)
        except (KeyError, TypeError, ValueError):
            continue
        if verify is not None and verify_tombstone is None:
            continue
        if verify_tombstone is not None and not verify_tombstone(tombstone):
            continue
        if store.merge_tombstone(tombstone):
            pulled += 1

    for raw in reply.get("records") or []:
        try:
            record = PresenceRecord.from_gossip_dict(raw)
        except (KeyError, TypeError, ValueError):
            continue
        if verify is not None and not verify(record):
            continue
        if store.merge_record(record):
            pulled += 1
    return (pushed, pulled)


def gossip_round(
    store,
    peers: List[str],
    *,
    fanout: int = 3,
    use_tls: bool = True,
    insecure_skip_verify: bool = False,
    verify=None,
    verify_tombstone=None,
    _select=None,
) -> int:
    """
    Gossip to up to ``fanout`` peers. ``peers`` are ``"host:port"``
    strings. Returns the number of peers successfully contacted (that
    merged or were merged from). ``_select`` is an injectable peer
    selector for deterministic tests; the default samples at random.
    """
    if not peers:
        return 0
    selector = _select or _default_select
    chosen = selector(peers, fanout)
    contacted = 0
    for endpoint in chosen:
        host, _, port_s = endpoint.rpartition(":")
        if not host or not port_s.isdigit():
            continue
        pushed, pulled = gossip_once(
            store, host, int(port_s),
            use_tls=use_tls, insecure_skip_verify=insecure_skip_verify,
            verify=verify, verify_tombstone=verify_tombstone,
        )
        if pushed or pulled:
            contacted += 1
    return contacted


def _default_select(peers: List[str], fanout: int) -> List[str]:
    import random
    if len(peers) <= fanout:
        return list(peers)
    return random.sample(peers, fanout)
