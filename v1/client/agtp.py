"""
AGTP client (v1).

Takes an `agtp://...` URI, resolves it to a serving host:port (via the
registry for bare-ID URIs, directly for `@host` URIs), connects, sends
DESCRIBE, and renders the response.

Usage:
  python agtp.py resolve agtp://72dd28d1...
  python agtp.py resolve agtp://72dd28d1... --format=json
  python agtp.py resolve agtp://72dd28d1... --format=yaml
  python agtp.py resolve agtp://72dd28d1... --format=html
  python agtp.py resolve agtp://72dd28d1...@agents.nomotic.ai
  python agtp.py resolve agtp://72dd28d1... --registry http://localhost:8080
"""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# Make the parent dir importable when run directly.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agent_id import parse_uri, ParsedURI, AgentIDError, DEFAULT_AGTP_PORT  # noqa: E402
from agent_document import (  # noqa: E402
    CONTENT_TYPE_HTML,
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_YAML,
)
import wire_v2 as wire  # noqa: E402


DEFAULT_REGISTRY_URL = "https://agtp.nomotic.ai"

# Map user-friendly format names to Accept header values.
FORMAT_TO_ACCEPT = {
    "json": CONTENT_TYPE_JSON,
    "agent.json": CONTENT_TYPE_JSON,
    "yaml": CONTENT_TYPE_YAML,
    "agent.yaml": CONTENT_TYPE_YAML,
    "html": CONTENT_TYPE_HTML,
}


class ResolutionError(Exception):
    """Raised when registry lookup or connection fails."""


def lookup_registry(agent_id: str, registry_url: str) -> tuple[str, int]:
    """
    Query the registry for an agent's serving host:port.

    Returns (host, port). Raises ResolutionError on miss or transport failure.
    """
    url = f"{registry_url.rstrip('/')}/registry/{agent_id}"
    try:
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ResolutionError(
                f"agent {agent_id} is not registered at {registry_url}"
            ) from exc
        raise ResolutionError(
            f"registry lookup failed: HTTP {exc.code}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ResolutionError(
            f"could not reach registry at {registry_url}: {exc.reason}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ResolutionError(f"registry returned invalid JSON: {exc}") from exc

    host = data.get("host")
    port = data.get("port")
    if not host or not port:
        raise ResolutionError(
            f"registry response missing host/port: {data!r}"
        )
    return host, int(port)


def resolve_target(
    parsed: ParsedURI, registry_url: str
) -> tuple[str, int]:
    """
    Determine the (host, port) to connect to for a parsed AGTP URI.

    If the URI has an explicit @host, use it directly.
    Otherwise, look up the registry.
    """
    if parsed.has_explicit_host:
        return parsed.host, parsed.effective_port
    return lookup_registry(parsed.agent_id, registry_url)


def fetch_agent_document(
    agent_id: str,
    host: str,
    port: int,
    accept: str,
    *,
    use_tls: bool = True,
    insecure_skip_verify: bool = False,
) -> wire.AGTPResponse:
    """
    Open a connection, send DESCRIBE, return the response.
    """
    sock = socket.create_connection((host, port), timeout=10.0)

    if use_tls:
        ctx = ssl.create_default_context()
        if insecure_skip_verify:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        sock = ctx.wrap_socket(sock, server_hostname=host)

    try:
        request = wire.AGTPRequest(
            method="DESCRIBE",
            headers={
                "Target-Agent": agent_id,
                "Accept": accept,
                "Host": host,
            },
        )
        sock.sendall(request.serialize())
        # Note: do not call shutdown(SHUT_WR) here. On TLS-wrapped sockets,
        # shutdown() sends a close_notify alert that terminates the session
        # before the server can respond. Content-Length framing handles
        # request boundaries without needing a half-close signal.
        reader = sock.makefile("rb")
        return wire.parse_response(reader)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def render_response(response: wire.AGTPResponse, accept: str) -> str:
    """
    Format the response body for terminal display.
    """
    body_text = response.body_bytes.decode("utf-8", errors="replace")

    if response.status_code != 200:
        return (
            f"AGTP/1.0 {response.status_code} {response.status_text}\n"
            f"\n{body_text}"
        )

    if accept == CONTENT_TYPE_JSON:
        try:
            parsed = json.loads(body_text)
            return json.dumps(parsed, indent=2)
        except json.JSONDecodeError:
            return body_text

    return body_text


def cmd_resolve(args) -> int:
    try:
        parsed = parse_uri(args.uri)
    except AgentIDError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    accept = FORMAT_TO_ACCEPT.get(args.format, CONTENT_TYPE_JSON)

    try:
        host, port = resolve_target(parsed, args.registry)
    except ResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"[client] resolved agtp://{parsed.agent_id[:12]}... "
        f"-> {host}:{port}",
        file=sys.stderr,
    )

    try:
        response = fetch_agent_document(
            parsed.agent_id,
            host,
            port,
            accept,
            use_tls=not args.insecure,
            insecure_skip_verify=args.insecure_skip_verify,
        )
    except (OSError, wire.WireFormatError) as exc:
        print(f"error: connection failed: {exc}", file=sys.stderr)
        return 1

    print(render_response(response, accept))
    return 0 if response.status_code == 200 else 1


def main() -> int:
    parser = argparse.ArgumentParser(prog="agtp", description="AGTP client")
    sub = parser.add_subparsers(dest="command", required=True)

    resolve = sub.add_parser("resolve", help="Resolve and fetch an agent document")
    resolve.add_argument("uri", help="agtp:// URI to resolve")
    resolve.add_argument(
        "--format",
        choices=list(FORMAT_TO_ACCEPT.keys()),
        default="json",
    )
    resolve.add_argument(
        "--registry",
        default=DEFAULT_REGISTRY_URL,
        help=f"Registry URL (default: {DEFAULT_REGISTRY_URL})",
    )
    resolve.add_argument(
        "--insecure",
        action="store_true",
        help="Connect plaintext (development only)",
    )
    resolve.add_argument(
        "--insecure-skip-verify",
        action="store_true",
        help="Skip TLS certificate verification (development only)",
    )

    args = parser.parse_args()

    if args.command == "resolve":
        return cmd_resolve(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
