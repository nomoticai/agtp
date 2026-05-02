"""
AGTP Agent Server (v1).

Hosts one or more Agent Documents and serves them over AGTP on port 4480.
TLS 1.3 is mandatory in production deployments per draft §5; the --cert
and --key flags enable it. For local development, --insecure permits
plaintext.

Method support (v1):
  DESCRIBE  Returns the Agent Identity Document. Content negotiated by Accept:
              application/vnd.agtp.identity+json   -> JSON  (default)
              application/vnd.agtp.identity+yaml   -> YAML
              text/html                            -> rendered identity card

Run:
  python agent_server.py --insecure --port 4480
  python agent_server.py --port 4480 --cert cert.pem --key key.pem

Deployment:
  Bind 0.0.0.0:4480 on a public host. DNS A record points at the host.
  TLS certificate covers the agent host (e.g., agents.nomotic.ai).
  Register each hosted agent with the registry so bare-ID URIs resolve.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
from pathlib import Path
from typing import Dict, Optional

# Make the parent dir importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import wire_v2 as wire  # noqa: E402
from agent_document import (  # noqa: E402
    AgentDocument,
    CONTENT_TYPE_HTML,
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_YAML,
    from_dict,
)
import renderer  # noqa: E402


DEFAULT_PORT = 4480


class AgentRegistry:
    """In-memory map of agent_id -> AgentDocument, loaded from disk."""

    def __init__(self, agents_dir: Path):
        self.agents_dir = agents_dir
        self.agents: Dict[str, AgentDocument] = {}
        self._load()

    def _load(self) -> None:
        if not self.agents_dir.exists():
            return
        for json_path in sorted(self.agents_dir.glob("*.agent.json")):
            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                doc = from_dict(data)
                self.agents[doc.agent_id] = doc
                print(f"[server] loaded {doc.name} ({doc.agent_id[:12]}...)")
            except (json.JSONDecodeError, ValueError) as exc:
                print(f"[server] skipping {json_path}: {exc}",
                      file=sys.stderr)

    def lookup(self, agent_id: str) -> Optional[AgentDocument]:
        return self.agents.get(agent_id)

    def list_ids(self) -> list[str]:
        return list(self.agents.keys())


def serve_describe(
    request: wire.AGTPRequest, registry: AgentRegistry
) -> wire.AGTPResponse:
    """
    Handle a DESCRIBE request by returning the Agent Document for the
    target agent in the requested format.

    Target-Agent header identifies which agent's document to return when
    the server hosts multiple agents.
    """
    target = _header(request, "Target-Agent")
    if not target:
        # If no Target-Agent and only one agent is hosted, default to it.
        ids = registry.list_ids()
        if len(ids) == 1:
            target = ids[0]
        else:
            return _error(
                400,
                "Bad Request",
                "missing-target-agent",
                "Target-Agent header required when server hosts multiple agents",
            )

    doc = registry.lookup(target)
    if doc is None:
        return _error(
            404,
            "Not Found",
            "agent-not-found",
            f"no agent with id {target} on this server",
        )

    accept = _header(request, "Accept", default=CONTENT_TYPE_JSON).lower()

    if "text/html" in accept:
        body = renderer.render_html(doc).encode("utf-8")
        content_type = CONTENT_TYPE_HTML
    elif "yaml" in accept:
        body = doc.to_yaml().encode("utf-8")
        content_type = CONTENT_TYPE_YAML
    else:
        body = doc.to_json(pretty=True).encode("utf-8")
        content_type = CONTENT_TYPE_JSON

    return wire.AGTPResponse(
        status_code=200,
        status_text="OK",
        headers={
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
            "Server-Agent-ID": doc.agent_id,
        },
        body_bytes=body,
    )


def _header(request: wire.AGTPRequest, name: str, default: str = "") -> str:
    lower = name.lower()
    for k, v in request.headers.items():
        if k.lower() == lower:
            return v
    return default


def _error(status: int, status_text: str, code: str, detail: str) -> wire.AGTPResponse:
    body = json.dumps({"error": {"code": code, "detail": detail}}).encode("utf-8")
    return wire.AGTPResponse(
        status_code=status,
        status_text=status_text,
        headers={
            "Content-Type": "application/json",
            "Content-Length": str(len(body)),
        },
        body_bytes=body,
    )


def handle_connection(conn, registry: AgentRegistry) -> None:
    """Handle a single AGTP connection: read one request, write one response."""
    try:
        reader = conn.makefile("rb")
        request = wire.parse_request(reader)
        method = request.method.upper()

        if method == "DESCRIBE":
            response = serve_describe(request, registry)
        else:
            response = _error(
                501,
                "Not Implemented",
                "method-not-implemented",
                f"{method} is not implemented in v1; only DESCRIBE is supported",
            )

        conn.sendall(response.serialize())
    except wire.WireFormatError as exc:
        try:
            conn.sendall(
                _error(400, "Bad Request", "invalid-wire-format", str(exc)).serialize()
            )
        except OSError:
            pass
    except OSError:
        pass
    finally:
        try:
            conn.shutdown(2)
        except OSError:
            pass
        conn.close()


def run(
    host: str,
    port: int,
    agents_dir: Path,
    certfile: Optional[str] = None,
    keyfile: Optional[str] = None,
) -> None:
    import socket
    import threading

    registry = AgentRegistry(agents_dir)
    if not registry.agents:
        print(f"[server] WARNING: no agents loaded from {agents_dir}",
              file=sys.stderr)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((host, port))
    sock.listen(64)

    if certfile and keyfile:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
        sock = ctx.wrap_socket(sock, server_side=True)
        scheme = "agtps"  # informal — used only for the log line
    else:
        scheme = "agtp"

    print(f"[server] listening on {scheme}://{host}:{port}")
    print(f"[server] agents: {len(registry.agents)} loaded")
    for agent_id, doc in registry.agents.items():
        print(f"[server]   {doc.name}: agtp://{agent_id}")

    try:
        while True:
            try:
                conn, addr = sock.accept()
            except ssl.SSLError as exc:
                print(f"[server] TLS handshake failed: {exc}", file=sys.stderr)
                continue
            t = threading.Thread(
                target=handle_connection, args=(conn, registry), daemon=True
            )
            t.start()
    except KeyboardInterrupt:
        print("\n[server] shutting down")
    finally:
        sock.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="AGTP Agent Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--agents-dir",
        default="agents",
        help="Directory containing *.agent.json files",
    )
    parser.add_argument("--cert", help="TLS certificate file")
    parser.add_argument("--key", help="TLS private key file")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Run plaintext (development only)",
    )
    args = parser.parse_args()

    if not args.insecure and not (args.cert and args.key):
        print(
            "[server] TLS required in production; pass --cert and --key, "
            "or --insecure for development",
            file=sys.stderr,
        )
        return 2

    run(args.host, args.port, Path(args.agents_dir), args.cert, args.key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
