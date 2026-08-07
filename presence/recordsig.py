"""
Presence-record signing (PDD §6.1 "Gossip" / §11.1).

A presence record can be signed by the announcing agent so that:

  * a relay or peer coordinator cannot **mutate** the record (change its
    capabilities, trust posture, or visibility) — any change breaks the
    signature; and
  * with the key→Agent-ID binding (:func:`binds_to_genesis`), a party
    cannot **forge** a record for an *existing* agent whose Agent-ID is the
    hash of a Genesis carrying a different public key.

The signature covers the canonical (RFC-8785-shaped) form of the record's
identity + discovery content, and the announcing agent's Ed25519 public key
is carried inline so a verifier can check integrity without a key lookup::

    record.signature = {
        "alg": "EdDSA",
        "payload_version": 2,
        "public_key": "<base64url raw 32 bytes>",
        "value":      "<base64url 64-byte signature>",
    }

Integrity verification (:func:`verify_record`) needs only the record.
Identity binding (:func:`binds_to_genesis`) additionally needs the agent's
Genesis; where a coordinator cannot resolve one (a foreign agent), it falls
back to integrity-only, which is trust-on-first-use for the key.

Version 2 authenticates the epoch and TTL used for record/tombstone conflict
resolution. Verification still accepts legacy version 1 records, but their
unauthenticated epoch cannot supersede a signed tombstone.
"""

from __future__ import annotations

import base64
import json
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey


SIGNING_ALG = "EdDSA"
RECORD_PAYLOAD_VERSION = 2
TOMBSTONE_PAYLOAD_VERSION = 1


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64url(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def signing_payload(record, *, payload_version: int = RECORD_PAYLOAD_VERSION) -> bytes:
    """
    Canonical bytes a signature covers: the record's identity and its
    discovery-facing content (so neither the identity nor what a query
    returns can be altered without detection). Deliberately excludes the
    signature itself and node-local fields (attachment).
    """
    payload = {
        "agent_id": record.agent_id,
        "result_entry": record.result_entry,
        "visibility": record.visibility.to_dict(),
        "scopes": list(record.scopes),
        "announced_at": record.announced_at,
    }
    if payload_version >= 2:
        # These fields decide expiry and record-vs-tombstone ordering. They
        # must be authenticated or a relay could advance an old record's
        # epoch and resurrect it after a withdrawal.
        payload["announced_at_epoch"] = record.announced_at_epoch
        payload["ttl_seconds"] = record.ttl_seconds
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def tombstone_signing_payload(tombstone) -> bytes:
    """Canonical, domain-separated bytes covered by a withdrawal signature."""
    payload = {
        "type": "agtp-presence-withdrawal",
        "agent_id": tombstone.agent_id,
        "withdrawn_at": tombstone.withdrawn_at,
        "withdrawn_at_epoch": tombstone.withdrawn_at_epoch,
        "retention_seconds": tombstone.retention_seconds,
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_record(record, signing_service) -> None:
    """
    Sign ``record`` in place with an agent's :class:`SigningService`,
    embedding the public key so verifiers need no key lookup.
    """
    signature = signing_service.sign(signing_payload(record))
    record.signature = {
        "alg": SIGNING_ALG,
        "payload_version": RECORD_PAYLOAD_VERSION,
        "public_key": _b64url(signing_service.public_key_raw()),
        "value": _b64url(signature),
    }


def sign_tombstone(tombstone, signing_service) -> None:
    """Sign a withdrawal tombstone in place with an Ed25519 key."""
    signature = signing_service.sign(tombstone_signing_payload(tombstone))
    tombstone.signature = {
        "alg": SIGNING_ALG,
        "payload_version": TOMBSTONE_PAYLOAD_VERSION,
        "public_key": _b64url(signing_service.public_key_raw()),
        "value": _b64url(signature),
    }


def signature_public_key_text(signed) -> Optional[str]:
    """Base64url public-key text carried by a signed presence object."""
    sig = signed.signature
    if not isinstance(sig, dict):
        return None
    value = sig.get("public_key")
    return value if isinstance(value, str) and value else None


def record_public_key(record) -> Optional[Ed25519PublicKey]:
    """The Ed25519 public key embedded in the record's signature, or None."""
    pk = signature_public_key_text(record)
    if pk is None:
        return None
    try:
        return Ed25519PublicKey.from_public_bytes(_unb64url(pk))
    except (ValueError, TypeError):
        return None


def verify_record(record) -> bool:
    """
    Integrity check: the record carries a well-formed EdDSA signature that
    verifies over its canonical content using the embedded public key.
    Returns False (never raises) for unsigned or tampered records.
    """
    sig = record.signature
    if not isinstance(sig, dict) or sig.get("alg") != SIGNING_ALG:
        return False
    value = sig.get("value")
    payload_version = sig.get("payload_version", 1)
    if payload_version not in (1, RECORD_PAYLOAD_VERSION):
        return False
    public_key = record_public_key(record)
    if public_key is None or not isinstance(value, str):
        return False
    try:
        public_key.verify(
            _unb64url(value),
            signing_payload(record, payload_version=payload_version),
        )
        return True
    except Exception:  # noqa: BLE001 - InvalidSignature and friends
        return False


def verify_tombstone(tombstone) -> bool:
    """Verify the signature and canonical content of a tombstone."""
    sig = tombstone.signature
    if not isinstance(sig, dict) or sig.get("alg") != SIGNING_ALG:
        return False
    value = sig.get("value")
    if sig.get("payload_version") != TOMBSTONE_PAYLOAD_VERSION:
        return False
    public_key = record_public_key(tombstone)
    if public_key is None or not isinstance(value, str):
        return False
    try:
        public_key.verify(_unb64url(value), tombstone_signing_payload(tombstone))
        return True
    except Exception:  # noqa: BLE001 - InvalidSignature and friends
        return False


def has_authenticated_conflict_epoch(record) -> bool:
    """Whether the record signature format covers its LWW/TTL fields."""
    sig = record.signature
    return (
        isinstance(sig, dict)
        and sig.get("alg") == SIGNING_ALG
        and sig.get("payload_version") == RECORD_PAYLOAD_VERSION
    )


def binds_to_genesis(record, genesis) -> bool:
    """
    Identity binding: the key that signed the record is the agent's Genesis
    key, and the Genesis hashes to the record's Agent-ID. Together with
    :func:`verify_record` this prevents forging a record for an existing
    agent (you would need that agent's private key).
    """
    if genesis is None:
        return False
    sig = record.signature if isinstance(record.signature, dict) else {}
    record_pk = sig.get("public_key")
    if not record_pk:
        return False
    try:
        from core.key_encoding import detect_format, pem_to_b64url_raw
        genesis_pk = genesis.agent_public_key or ""
        if detect_format(genesis_pk) == "pem":
            genesis_pk = pem_to_b64url_raw(genesis_pk)
        genesis_pk = genesis_pk.strip()
    except Exception:  # noqa: BLE001
        return False
    if record_pk.strip() != genesis_pk:
        return False
    try:
        return genesis.canonical_agent_id() == record.agent_id
    except Exception:  # noqa: BLE001
        return False
