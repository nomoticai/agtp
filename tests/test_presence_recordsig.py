"""
AGTP-Presence M3 — presence-record signing: integrity, key→Agent-ID
binding, signed foreign ANNOUNCE, and gossip signature verification.
"""

from __future__ import annotations

import json
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from client.core_client import send_method
from core.genesis import AgentGenesis, public_key_pem, utc_now_iso
from presence import client as pc
from presence import gossip as g
from presence import recordsig as rs
from presence.records import PresenceRecord, PresenceTombstone, Visibility
from presence.store import PresenceStore
from presence.testing import InProcessCoordinator, make_doc
from server.signing import SigningService


def _record(agent_id, name="agent", caps=("validate",), tier=2):
    return PresenceRecord(
        agent_id=agent_id,
        result_entry={
            "agent_id": agent_id, "manifest_uri": f"agtp://{agent_id}",
            "name": name, "supported_methods": ["VALIDATE"],
            "capabilities": list(caps), "trust_tier": tier,
        },
        visibility=Visibility(),
    )


# ---------------------------------------------------------------------------
# Integrity.
# ---------------------------------------------------------------------------


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.svc = SigningService(private_key=Ed25519PrivateKey.generate())

    def test_unsigned_does_not_verify(self):
        self.assertFalse(rs.verify_record(_record("a" * 64)))

    def test_sign_then_verify(self):
        rec = _record("a" * 64)
        rs.sign_record(rec, self.svc)
        self.assertEqual(rec.signature["alg"], "EdDSA")
        self.assertTrue(rs.verify_record(rec))

    def test_tampered_result_entry_fails(self):
        rec = _record("a" * 64)
        rs.sign_record(rec, self.svc)
        rec.result_entry["trust_tier"] = 1  # promote self
        self.assertFalse(rs.verify_record(rec))

    def test_tampered_visibility_fails(self):
        rec = _record("a" * 64)
        rs.sign_record(rec, self.svc)
        rec.visibility = Visibility(presence_mode="invisible")
        self.assertFalse(rs.verify_record(rec))

    def test_tampered_conflict_epoch_fails(self):
        rec = _record("a" * 64)
        rs.sign_record(rec, self.svc)
        rec.announced_at_epoch += 10_000
        self.assertFalse(rs.verify_record(rec))

    def test_sign_then_verify_tombstone(self):
        tombstone = PresenceTombstone(agent_id="a" * 64)
        rs.sign_tombstone(tombstone, self.svc)
        self.assertTrue(rs.verify_tombstone(tombstone))
        tombstone.withdrawn_at_epoch += 1
        self.assertFalse(rs.verify_tombstone(tombstone))

    def test_gossip_roundtrip_preserves_signature(self):
        rec = _record("a" * 64)
        rs.sign_record(rec, self.svc)
        clone = PresenceRecord.from_gossip_dict(rec.to_gossip_dict())
        self.assertTrue(rs.verify_record(clone))


# ---------------------------------------------------------------------------
# Key -> Agent-ID binding via Genesis.
# ---------------------------------------------------------------------------


class BindingTests(unittest.TestCase):
    def _genesis_and_key(self):
        agent_key = Ed25519PrivateKey.generate()
        genesis = AgentGenesis(
            name="auditor", owner_id="acme.tld", principal_id="chris@acme",
            agent_public_key=public_key_pem(agent_key.public_key()),
            issued_at=utc_now_iso(), issuer="self",
            issuer_public_key=public_key_pem(agent_key.public_key()),
            trust_tier=2,
        )
        genesis.sign(agent_key)
        return genesis, agent_key

    def test_binding_holds_for_matching_key_and_id(self):
        genesis, agent_key = self._genesis_and_key()
        aid = genesis.canonical_agent_id()
        rec = _record(aid)
        rs.sign_record(rec, SigningService(private_key=agent_key))
        self.assertTrue(rs.verify_record(rec))
        self.assertTrue(rs.binds_to_genesis(rec, genesis))

    def test_binding_fails_for_wrong_key(self):
        genesis, _ = self._genesis_and_key()
        aid = genesis.canonical_agent_id()
        rec = _record(aid)
        rs.sign_record(rec, SigningService(private_key=Ed25519PrivateKey.generate()))
        # Signature is valid (integrity) but the key is not the Genesis key.
        self.assertTrue(rs.verify_record(rec))
        self.assertFalse(rs.binds_to_genesis(rec, genesis))

    def test_binding_fails_for_wrong_agent_id(self):
        genesis, agent_key = self._genesis_and_key()
        rec = _record("b" * 64)  # not the Genesis hash
        rs.sign_record(rec, SigningService(private_key=agent_key))
        self.assertFalse(rs.binds_to_genesis(rec, genesis))


# ---------------------------------------------------------------------------
# Signed foreign ANNOUNCE over the wire.
# ---------------------------------------------------------------------------


class ForeignAnnounceTests(unittest.TestCase):
    def test_signed_foreign_announce_accepted_and_discoverable(self):
        coord = InProcessCoordinator([]).start()  # hosts nothing
        try:
            key = SigningService(private_key=Ed25519PrivateKey.generate())
            rec = _record("f" * 64, name="foreign")
            r = pc.announce_signed_record(coord.host, coord.port, rec, key, use_tls=False)
            self.assertEqual(r.status_code, 200)
            self.assertTrue(json.loads(r.body_bytes.decode())["verified"])
            replay = pc.announce_signed_record(
                coord.host, coord.port, rec, key, use_tls=False
            )
            self.assertEqual(replay.status_code, 200)
            d = pc.discover_population_json(
                coord.host, coord.port, capability="validate", use_tls=False
            )
            self.assertEqual(d["total_matches"], 1)
            self.assertEqual(d["results"][0]["name"], "foreign")
        finally:
            coord.stop()

    def test_unsigned_foreign_announce_rejected(self):
        coord = InProcessCoordinator([]).start()
        try:
            rec = _record("g" * 64, name="evil")
            body = json.dumps({"record": rec.to_gossip_dict()}).encode("utf-8")
            r = send_method(
                None, coord.host, coord.port, "ANNOUNCE",
                body=body, body_content_type="application/json", use_tls=False,
            )
            self.assertEqual(r.status_code, 403)
            self.assertEqual(
                json.loads(r.body_bytes.decode())["error"]["code"],
                "announce-signature-invalid",
            )
        finally:
            coord.stop()

    def test_mutated_after_signing_rejected(self):
        coord = InProcessCoordinator([]).start()
        try:
            key = SigningService(private_key=Ed25519PrivateKey.generate())
            rec = _record("h" * 64, name="ok")
            rs.sign_record(rec, key)
            gossip_dict = rec.to_gossip_dict()
            gossip_dict["result_entry"]["trust_tier"] = 1  # tamper in transit
            body = json.dumps({"record": gossip_dict}).encode("utf-8")
            r = send_method(
                None, coord.host, coord.port, "ANNOUNCE",
                body=body, body_content_type="application/json", use_tls=False,
            )
            self.assertEqual(r.status_code, 403)
        finally:
            coord.stop()

    def test_signed_foreign_withdraw_accepted(self):
        coord = InProcessCoordinator([]).start()
        try:
            key = SigningService(private_key=Ed25519PrivateKey.generate())
            rec = _record("9" * 64, name="foreign")
            announced = pc.announce_signed_record(
                coord.host, coord.port, rec, key, use_tls=False
            )
            self.assertEqual(announced.status_code, 200)

            withdrawn = pc.withdraw(
                coord.host,
                coord.port,
                rec.agent_id,
                signing_service=key,
                use_tls=False,
            )
            self.assertEqual(withdrawn.status_code, 200)
            self.assertIsNone(coord.store.probe(rec.agent_id))
            body = json.loads(withdrawn.body_bytes.decode())
            self.assertTrue(rs.verify_tombstone(
                PresenceTombstone.from_gossip_dict(body["tombstone"])
            ))
        finally:
            coord.stop()


# ---------------------------------------------------------------------------
# Gossip signature verification.
# ---------------------------------------------------------------------------


class GossipVerifyTests(unittest.TestCase):
    def _signed_source(self):
        store = PresenceStore()
        key = SigningService(private_key=Ed25519PrivateKey.generate())
        rec = _record("a" * 64, name="good")
        rs.sign_record(rec, key)
        store.announce(rec)
        return store

    def test_valid_signed_record_merges(self):
        src = self._signed_source()
        dst = PresenceStore()
        reply = g.apply_replicate(dst, g.build_replicate_request(src), verify=rs.verify_record)
        self.assertEqual(reply["merged"], 1)
        self.assertEqual(reply["rejected"], 0)

    def test_mutated_record_rejected(self):
        src = self._signed_source()
        req = g.build_replicate_request(src)
        req["records"][0]["result_entry"]["trust_tier"] = 1  # mutate in transit
        dst = PresenceStore()
        reply = g.apply_replicate(dst, req, verify=rs.verify_record)
        self.assertEqual(reply["merged"], 0)
        self.assertEqual(reply["rejected"], 1)

    def test_unsigned_rejected_in_verify_mode(self):
        src = PresenceStore()
        src.announce(_record("a" * 64))  # unsigned
        dst = PresenceStore()
        reply = g.apply_replicate(dst, g.build_replicate_request(src), verify=rs.verify_record)
        self.assertEqual(reply["merged"], 0)

    def test_unsigned_accepted_without_verify(self):
        # Back-compat: no verify predicate → unsigned records still flow.
        src = PresenceStore()
        src.announce(_record("a" * 64))
        dst = PresenceStore()
        reply = g.apply_replicate(dst, g.build_replicate_request(src))
        self.assertEqual(reply["merged"], 1)

    def test_different_signer_cannot_delete_signed_record(self):
        owner = SigningService(private_key=Ed25519PrivateKey.generate())
        attacker = SigningService(private_key=Ed25519PrivateKey.generate())
        rec = _record("a" * 64)
        rec.announced_at_epoch = 100.0
        rec.ttl_seconds = 0
        rs.sign_record(rec, owner)
        dst = PresenceStore()
        dst.announce(rec)

        tombstone = PresenceTombstone(
            agent_id=rec.agent_id,
            withdrawn_at_epoch=200.0,
            retention_seconds=0,
        )
        rs.sign_tombstone(tombstone, attacker)
        src = PresenceStore()
        self.assertTrue(src.merge_tombstone(tombstone, verify=rs.verify_tombstone))

        reply = g.apply_replicate(
            dst,
            g.build_replicate_request(src),
            verify=rs.verify_record,
            verify_tombstone=rs.verify_tombstone,
        )
        self.assertEqual(reply["tombstones_merged"], 0)
        self.assertIsNotNone(dst.probe(rec.agent_id))

    def test_newer_same_signer_record_supersedes_tombstone(self):
        owner = SigningService(private_key=Ed25519PrivateKey.generate())
        store = PresenceStore()
        rec = _record("a" * 64, name="v1")
        rec.announced_at_epoch = 100.0
        rec.ttl_seconds = 0
        rs.sign_record(rec, owner)
        store.announce(rec)

        tombstone = PresenceTombstone(
            agent_id=rec.agent_id,
            withdrawn_at_epoch=200.0,
            retention_seconds=0,
        )
        rs.sign_tombstone(tombstone, owner)
        self.assertTrue(store.merge_tombstone(
            tombstone, verify=rs.verify_tombstone
        ))

        replacement = _record("a" * 64, name="v2")
        replacement.announced_at_epoch = 300.0
        replacement.ttl_seconds = 0
        rs.sign_record(replacement, owner)
        self.assertTrue(store.merge_record(replacement))
        self.assertEqual(store.probe(rec.agent_id).result_entry["name"], "v2")

    def test_partition_rejoin_converges_on_signed_withdrawal(self):
        signing = SigningService(private_key=Ed25519PrivateKey.generate())
        coord_a = InProcessCoordinator(
            [make_doc("a" * 64, "worker", ["VALIDATE"])],
            signing_service=signing,
            verify_signatures=True,
        ).start()
        coord_b = InProcessCoordinator(
            [], verify_signatures=True
        ).start()
        try:
            # Connected: B first learns A's signed live record.
            g.gossip_once(
                coord_a.store,
                coord_b.host,
                coord_b.port,
                use_tls=False,
                verify=rs.verify_record,
                verify_tombstone=rs.verify_tombstone,
            )
            self.assertIsNotNone(coord_b.store.probe("a" * 64))

            # Partition: no gossip occurs while A withdraws; B stays stale.
            response = pc.withdraw(
                coord_a.host, coord_a.port, "a" * 64, use_tls=False
            )
            self.assertEqual(response.status_code, 200)
            self.assertIsNone(coord_a.store.probe("a" * 64))
            self.assertIsNotNone(coord_b.store.probe("a" * 64))

            # Rejoin from the stale side. A rejects B's old live record and
            # returns its tombstone; B applies it in the same round.
            g.gossip_once(
                coord_b.store,
                coord_a.host,
                coord_a.port,
                use_tls=False,
                verify=rs.verify_record,
                verify_tombstone=rs.verify_tombstone,
            )
            self.assertIsNone(coord_a.store.probe("a" * 64))
            self.assertIsNone(coord_b.store.probe("a" * 64))

            # A further round must not resurrect the withdrawn record.
            g.gossip_once(
                coord_a.store,
                coord_b.host,
                coord_b.port,
                use_tls=False,
                verify=rs.verify_record,
                verify_tombstone=rs.verify_tombstone,
            )
            self.assertIsNone(coord_a.store.probe("a" * 64))
            self.assertIsNone(coord_b.store.probe("a" * 64))
        finally:
            coord_a.stop()
            coord_b.stop()


class HostedSigningTests(unittest.TestCase):
    def test_signing_coordinator_signs_hosted_records(self):
        svc = SigningService(private_key=Ed25519PrivateKey.generate())
        coord = InProcessCoordinator(
            [make_doc("a" * 64, "worker", ["VALIDATE"], tier=1)],
            signing_service=svc,
        ).start()
        try:
            rec = coord.store.probe("a" * 64)
            self.assertIsNotNone(rec.signature)
            self.assertTrue(rs.verify_record(rec))
        finally:
            coord.stop()


if __name__ == "__main__":
    unittest.main()
