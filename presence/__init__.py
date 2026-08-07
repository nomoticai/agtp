"""
AGTP Presence — substrate-level ambient discovery.

Presence inverts the pull-based discovery model: when an agent joins the
substrate it announces its intrinsic posture and becomes ambiently
visible to the relevant scope of peers, without a separate publishing
step. "Showing up is the registration" (the DHCP analogy from the PDD
§1.4).

This package implements the coordinator-side slices of that design:

  * :mod:`presence.records`  — live record and withdrawal tombstone shapes.
  * :mod:`presence.scopes`   — scope tuples and capability derivation.
  * :mod:`presence.store`    — TTL-aware in-memory coordinator state.
  * :mod:`presence.gossip`   — peer anti-entropy and deletion convergence.
  * :mod:`presence.methods`  — ANNOUNCE / WITHDRAW / PROBE handlers and
                               the ``DISCOVER /population`` query.

The coordinator is an ordinary AGTP server (``python -m server
--presence``) with a :class:`presence.store.PresenceStore` attached. The
server's connection handler routes presence verbs and the
``/population`` DISCOVER path to :func:`presence.methods.maybe_handle_presence`
only when that store is present, so a plain agent server is unaffected.
"""

from presence.records import PresenceRecord, PresenceTombstone, Visibility
from presence.store import PresenceStore

__all__ = ["PresenceRecord", "PresenceTombstone", "Visibility", "PresenceStore"]
