"""
The in-memory presence store — M1 coordinator state.

A coordinator holds every live :class:`PresenceRecord` keyed by Agent-ID,
retained withdrawal tombstones, and a capability -> {agent_id} inverted
index. The store applies TTL aging and the conflict rules used by gossip
anti-entropy. DHT k-bucket routing remains a separate layer.

Thread-safety: the AGTP server handles each connection on its own thread,
so every mutation and read takes ``self._lock``.
"""

from __future__ import annotations

import threading
import time
from typing import Dict, List, Optional, Set

from core.identity import AgentDocument
from presence import recordsig as _recordsig
from presence import scopes as _scopes
from presence.records import (
    DEFAULT_TOMBSTONE_RETENTION_SECONDS,
    DEFAULT_TTL_SECONDS,
    PresenceRecord,
    PresenceTombstone,
    Visibility,
)


class PresenceStore:
    """Coordinator-held map of Agent-ID -> PresenceRecord."""

    def __init__(
        self,
        *,
        tombstone_retention_seconds: int = DEFAULT_TOMBSTONE_RETENTION_SECONDS,
    ) -> None:
        try:
            retention = int(tombstone_retention_seconds)
            valid_retention = (
                not isinstance(tombstone_retention_seconds, bool)
                and retention >= 0
                and retention == float(tombstone_retention_seconds)
            )
        except (TypeError, ValueError, OverflowError):
            valid_retention = False
        if not valid_retention:
            raise ValueError(
                "tombstone_retention_seconds must be a non-negative integer"
            )
        self._lock = threading.RLock()
        self.tombstone_retention_seconds = retention
        self._records: Dict[str, PresenceRecord] = {}
        self._tombstones: Dict[str, PresenceTombstone] = {}
        self._tombstone_expires_at: Dict[str, Optional[float]] = {}
        #: capability token -> set of agent_ids carrying it.
        self._by_capability: Dict[str, Set[str]] = {}

    # -- mutation -----------------------------------------------------

    def announce(
        self, record: PresenceRecord, *, now: Optional[float] = None
    ) -> bool:
        """Insert a presence record if it wins the current conflict state.

        A record newer than a retained tombstone may re-announce the agent,
        but a signed tombstone can only be superseded by the same signing
        key. Returns True if the local view changed.
        """
        _now = time.time() if now is None else now
        try:
            record.validate()
        except (TypeError, ValueError, OverflowError):
            return False
        with self._lock:
            self._sweep_locked(_now)
            self._sweep_tombstones_locked(_now)
            existing = self._records.get(record.agent_id)
            if (
                existing is not None
                and existing.to_gossip_dict() == record.to_gossip_dict()
            ):
                return True  # idempotent replay of the same announcement
        return self.merge_record(record, now=_now)

    def withdraw(
        self,
        agent_id: str,
        tombstone: Optional[PresenceTombstone] = None,
        *,
        now: Optional[float] = None,
    ) -> bool:
        """Replace a live record with a retained withdrawal tombstone.

        Callers operating a signed store must supply a tombstone signed by
        the same key as the current record. Unsigned tombstones remain
        available for the existing non-verifying development mode.
        """
        _now = time.time() if now is None else now
        with self._lock:
            self._sweep_locked(_now)
            self._sweep_tombstones_locked(_now)
            if agent_id not in self._records:
                return False
            candidate = tombstone or PresenceTombstone(agent_id=agent_id)
            if candidate.agent_id != agent_id:
                return False
            try:
                candidate.validate()
            except (TypeError, ValueError, OverflowError):
                return False
            return self._merge_tombstone_locked(candidate, now=_now)

    def _drop_indexes(self, agent_id: str) -> None:
        for cap, ids in list(self._by_capability.items()):
            ids.discard(agent_id)
            if not ids:
                self._by_capability.pop(cap, None)

    # -- read ---------------------------------------------------------

    def probe(
        self, agent_id: str, *, now: Optional[float] = None
    ) -> Optional[PresenceRecord]:
        """
        Return the record for ``agent_id``, or None if not present or
        aged out. TTL is applied lazily here so a probe never returns a
        stale record; ``now`` is injectable for deterministic tests.
        """
        _now = time.time() if now is None else now
        with self._lock:
            record = self._records.get(agent_id)
            if record is None:
                return None
            if record.is_expired(_now):
                self._drop_indexes(agent_id)
                self._records.pop(agent_id, None)
                return None
            return record

    def query_population(
        self,
        *,
        capability: Optional[str] = None,
        tier: Optional[int] = None,
        owner_domain: Optional[str] = None,
        limit: Optional[int] = None,
        now: Optional[float] = None,
    ) -> List[PresenceRecord]:
        """
        Return live records matching the filter, ordered by Agent-ID for a
        stable result (M1 has no ranking; ranking lands in M3).

        Filters compose (logical AND) across the partition dimensions we
        carry today — ``capability`` (via the derived index), ``tier``,
        and ``owner_domain`` — the M2 realization of multi-overlay
        membership. Expired records are swept lazily first. ``now`` is
        injectable for deterministic tests.
        """
        _now = time.time() if now is None else now
        with self._lock:
            self._sweep_locked(_now)
            if capability is None:
                candidates = list(self._records.values())
            else:
                ids = self._by_capability.get(capability.strip().lower(), set())
                candidates = [self._records[i] for i in ids if i in self._records]

            if tier is not None:
                candidates = [
                    r for r in candidates
                    if r.result_entry.get("trust_tier") == tier
                ]
            if owner_domain is not None:
                candidates = [r for r in candidates if r.owner_domain == owner_domain]

            candidates.sort(key=lambda r: r.agent_id)
            if limit is not None and limit >= 0:
                candidates = candidates[:limit]
            return candidates

    # -- anti-entropy (gossip) ---------------------------------------

    def all_records(self, *, now: Optional[float] = None) -> List[PresenceRecord]:
        """Every live record (expired swept first). Used to build a
        gossip push set."""
        _now = time.time() if now is None else now
        with self._lock:
            self._sweep_locked(_now)
            return list(self._records.values())

    def digest(self, *, now: Optional[float] = None) -> Dict[str, float]:
        """``{agent_id: announced_at_epoch}`` for every live record — the
        compact summary a peer diffs against to decide what it needs."""
        _now = time.time() if now is None else now
        with self._lock:
            self._sweep_locked(_now)
            return {aid: rec.announced_at_epoch for aid, rec in self._records.items()}

    def all_tombstones(
        self, *, now: Optional[float] = None
    ) -> List[PresenceTombstone]:
        """Every retained withdrawal tombstone, for gossip push."""
        _now = time.time() if now is None else now
        with self._lock:
            self._sweep_tombstones_locked(_now)
            return list(self._tombstones.values())

    def tombstone_digest(self, *, now: Optional[float] = None) -> Dict[str, float]:
        """``{agent_id: withdrawn_at_epoch}`` for retained tombstones."""
        _now = time.time() if now is None else now
        with self._lock:
            self._sweep_tombstones_locked(_now)
            return {
                aid: tomb.withdrawn_at_epoch
                for aid, tomb in self._tombstones.items()
            }

    def merge_record(
        self, record: PresenceRecord, *, now: Optional[float] = None
    ) -> bool:
        """
        Merge a record received from a peer. Keeps the most recent by
        ``announced_at_epoch`` (last-writer-wins on announce time, per the
        PDD conflict rule). Returns True if the local view changed.
        """
        _now = time.time() if now is None else now
        try:
            record.validate()
        except (TypeError, ValueError, OverflowError):
            return False
        if record.is_expired(_now):
            return False
        with self._lock:
            self._sweep_locked(_now)
            self._sweep_tombstones_locked(_now)
            tombstone = self._tombstones.get(record.agent_id)
            if tombstone is not None:
                if tombstone.withdrawn_at_epoch >= record.announced_at_epoch:
                    return False
                if not self._same_signer(tombstone, record):
                    return False
                if (
                    _recordsig.signature_public_key_text(tombstone) is not None
                    and not _recordsig.has_authenticated_conflict_epoch(record)
                ):
                    return False
            existing = self._records.get(record.agent_id)
            if existing is not None and existing.announced_at_epoch >= record.announced_at_epoch:
                return False
            self._drop_indexes(record.agent_id)
            self._tombstones.pop(record.agent_id, None)
            self._tombstone_expires_at.pop(record.agent_id, None)
            self._records[record.agent_id] = record
            for cap in record.result_entry.get("capabilities", []):
                self._by_capability.setdefault(cap, set()).add(record.agent_id)
            return True

    def merge_tombstone(
        self,
        tombstone: PresenceTombstone,
        *,
        verify=None,
        now: Optional[float] = None,
    ) -> bool:
        """Merge an authenticated withdrawal received from a peer.

        ``verify`` is an optional cryptographic predicate. Independently of
        it, signer continuity is enforced whenever the local live record or
        prior tombstone has an embedded key.
        """
        try:
            tombstone.validate()
        except (TypeError, ValueError, OverflowError):
            return False
        if verify is not None and not verify(tombstone):
            return False
        _now = time.time() if now is None else now
        with self._lock:
            self._sweep_locked(_now)
            self._sweep_tombstones_locked(_now)
            return self._merge_tombstone_locked(tombstone, now=_now)

    def _merge_tombstone_locked(
        self, tombstone: PresenceTombstone, *, now: float
    ) -> bool:
        previous = self._tombstones.get(tombstone.agent_id)
        if previous is not None:
            if previous.withdrawn_at_epoch >= tombstone.withdrawn_at_epoch:
                return False
            if not self._same_signer(previous, tombstone):
                return False

        record = self._records.get(tombstone.agent_id)
        if record is not None:
            if not self._same_signer(record, tombstone):
                return False
            record_is_signed = _recordsig.signature_public_key_text(record) is not None
            if (
                (not record_is_signed or _recordsig.has_authenticated_conflict_epoch(record))
                and record.announced_at_epoch > tombstone.withdrawn_at_epoch
            ):
                return False

        expiry = self._retention_deadline(now)
        if previous is not None:
            previous_expiry = self._tombstone_expires_at.get(tombstone.agent_id)
            if previous_expiry is None or expiry is None:
                expiry = None
            else:
                expiry = max(previous_expiry, expiry)

        self._drop_indexes(tombstone.agent_id)
        self._records.pop(tombstone.agent_id, None)
        self._tombstones[tombstone.agent_id] = tombstone
        self._tombstone_expires_at[tombstone.agent_id] = expiry
        return True

    def _retention_deadline(self, received_at: float) -> Optional[float]:
        """Local GC deadline, measured from this receiver's first merge."""
        if self.tombstone_retention_seconds == 0:
            return None
        return received_at + self.tombstone_retention_seconds

    @staticmethod
    def _same_signer(existing, incoming) -> bool:
        """Require key continuity when the existing state is signed."""
        existing_key = _recordsig.signature_public_key_text(existing)
        if existing_key is None:
            return True
        return existing_key == _recordsig.signature_public_key_text(incoming)

    def records_peer_needs(
        self,
        remote_digest: Dict[str, float],
        *,
        remote_tombstone_digest: Optional[Dict[str, float]] = None,
        now: Optional[float] = None,
    ) -> List[PresenceRecord]:
        """
        The live records a peer is missing or holds a staler copy of, given
        the peer's digest. This is the delta returned to a gossip sender.
        """
        _now = time.time() if now is None else now
        with self._lock:
            self._sweep_locked(_now)
            out = []
            for aid, rec in self._records.items():
                remote_epoch = self._digest_epoch(remote_digest, aid)
                remote_withdraw = self._digest_epoch(
                    remote_tombstone_digest or {}, aid
                )
                remote_state = max(
                    epoch for epoch in (remote_epoch, remote_withdraw)
                    if epoch is not None
                ) if remote_epoch is not None or remote_withdraw is not None else None
                if remote_state is None or rec.announced_at_epoch > remote_state:
                    out.append(rec)
            return out

    def tombstones_peer_needs(
        self,
        remote_digest: Dict[str, float],
        *,
        now: Optional[float] = None,
    ) -> List[PresenceTombstone]:
        """Retained tombstones a peer lacks or holds an older copy of."""
        _now = time.time() if now is None else now
        with self._lock:
            self._sweep_tombstones_locked(_now)
            out = []
            for aid, tombstone in self._tombstones.items():
                remote_epoch = self._digest_epoch(remote_digest, aid)
                if (
                    remote_epoch is None
                    or tombstone.withdrawn_at_epoch > remote_epoch
                ):
                    out.append(tombstone)
            return out

    @staticmethod
    def _digest_epoch(digest: Dict[str, float], agent_id: str) -> Optional[float]:
        try:
            value = digest.get(agent_id)
            return None if value is None else float(value)
        except (AttributeError, TypeError, ValueError):
            return None

    def sweep_expired(self, now: Optional[float] = None) -> int:
        """
        Evict every record past its TTL. Returns the count evicted. Called
        lazily on read and, in coordinator mode, from a background thread.
        """
        _now = time.time() if now is None else now
        with self._lock:
            removed = self._sweep_locked(_now)
            self._sweep_tombstones_locked(_now)
            return removed

    def _sweep_locked(self, now: float) -> int:
        expired = [
            aid for aid, rec in self._records.items() if rec.is_expired(now)
        ]
        for aid in expired:
            self._drop_indexes(aid)
            self._records.pop(aid, None)
        return len(expired)

    def _sweep_tombstones_locked(self, now: float) -> int:
        expired = [
            aid for aid in self._tombstones
            if self._tombstone_expires_at.get(aid) is not None
            and now >= self._tombstone_expires_at[aid]
        ]
        for aid in expired:
            self._tombstones.pop(aid, None)
            self._tombstone_expires_at.pop(aid, None)
        return len(expired)

    def count(self, *, now: Optional[float] = None) -> int:
        """Live population size (expired records swept first)."""
        _now = time.time() if now is None else now
        with self._lock:
            self._sweep_locked(_now)
            return len(self._records)

    # -- record construction -----------------------------------------

    def build_tombstone(
        self,
        agent_id: str,
    ) -> PresenceTombstone:
        """Build an unsigned tombstone ready for the caller to sign."""
        return PresenceTombstone(agent_id=agent_id)

    def build_record(
        self,
        agent_doc: AgentDocument,
        *,
        relay_endpoint: Optional[str] = None,
        visibility: Optional[Visibility] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> PresenceRecord:
        """
        Build a :class:`PresenceRecord` from a hosted AgentDocument.

        The ``result_entry`` is the discovery-safe projection: identity,
        derived capabilities, supported methods, and trust posture — and
        crucially **no network address**. ``manifest_uri`` is the bare
        Agent-ID URI (``agtp://<agent-id>``), which resolves through the
        coordinator/relay rather than to an agent-held endpoint.

        Used both by boot-time self-announce (coordinator mode) and by the
        ANNOUNCE handler.
        """
        caps = sorted(_scopes.derive_capabilities(agent_doc))
        entry = {
            "agent_id": agent_doc.agent_id,
            "manifest_uri": f"agtp://{agent_doc.agent_id}",
            "name": agent_doc.name,
            "supported_methods": list(agent_doc.requires.methods),
            "capabilities": caps,
            "trust_tier": agent_doc.trust_tier,
            "verification_path": agent_doc.verification_path,
        }
        if agent_doc.trust_score is not None:
            entry["behavioral_trust_score"] = agent_doc.trust_score
        if agent_doc.trust_warning:
            entry["trust_warning"] = agent_doc.trust_warning
        if agent_doc.owner_id:
            entry["owner_id"] = agent_doc.owner_id

        attachment = (
            {"mode": "relay-mediated", "relay": relay_endpoint}
            if relay_endpoint
            else None
        )
        return PresenceRecord(
            agent_id=agent_doc.agent_id,
            result_entry=entry,
            scopes=_scopes.default_scopes(agent_doc),
            visibility=visibility or Visibility(),
            owner_domain=agent_doc.owner_id or None,
            attachment=attachment,
            ttl_seconds=ttl_seconds,
        )
