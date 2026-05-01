"""
AGTP client (v1).

Resolves `agtp://...` URIs and fetches the agent's identity document.

Usage:
  agtp agtp://d8dc6f0d...               # JSON to stdout (default)
  agtp agtp://d8dc6f0d... --json        # explicit JSON
  agtp agtp://d8dc6f0d... --yaml        # YAML to stdout
  agtp agtp://d8dc6f0d... --html        # open identity card in browser
  agtp agtp://d8dc6f0d... -v            # verbose: show resolution steps

  # Direct host form (bypasses registry):
  agtp agtp://d8dc6f0d...@agents.agtp.io

  # Override registry (for testing alternative registries):
  agtp agtp://d8dc6f0d... --registry https://other-registry.example
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
import webbrowser
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


# The canonical AGTP registry. Baked in as the default — same way DNS
# clients have a default resolver baked in. Users override only when
# testing alternative registries.
DEFAULT_REGISTRY_URL = "https://registry.agtp.io"


class ResolutionError(Exception):
    """Raised when registry lookup or connection fails."""


def lookup_registry(
    agent_id: str, registry_url: str, *, verbose: bool = False
) -> tuple[str, int]:
    """
    Query the registry for an agent's serving host:port.
    Returns (host, port). Raises ResolutionError on miss or transport failure.
    """
    url = f"{registry_url.rstrip('/')}/registry/{agent_id}"
    if verbose:
        print(f"[client] registry lookup: {url}", file=sys.stderr)
    try:
        with urllib.request.urlopen(url, timeout=5.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ResolutionError(
                f"agent {agent_id} is not registered at {registry_url}"
            ) from exc
        raise ResolutionError(f"registry lookup failed: HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ResolutionError(
            f"could not reach registry at {registry_url}: {exc.reason}"
        ) from exc
    except json.JSONDecodeError as exc:
        raise ResolutionError(f"registry returned invalid JSON: {exc}") from exc

    host = data.get("host")
    port = data.get("port")
    if not host or not port:
        raise ResolutionError(f"registry response missing host/port: {data!r}")
    return host, int(port)


def resolve_target(
    parsed: ParsedURI, registry_url: str, *, verbose: bool = False
) -> tuple[str, int]:
    """
    Determine (host, port) for a parsed AGTP URI.
    Form 1a (`agent-id@host`) uses the embedded host directly.
    Form 1 (bare ID) requires a registry lookup.
    """
    if parsed.has_explicit_host:
        if verbose:
            print(
                f"[client] direct: {parsed.host}:{parsed.effective_port}",
                file=sys.stderr,
            )
        return parsed.host, parsed.effective_port
    return lookup_registry(parsed.agent_id, registry_url, verbose=verbose)


def fetch_agent_document(
    agent_id: str,
    host: str,
    port: int,
    accept: str,
    *,
    use_tls: bool = True,
    insecure_skip_verify: bool = False,
    verbose: bool = False,
) -> wire.AGTPResponse:
    """Open AGTP connection, send DESCRIBE, return the response."""
    if verbose:
        scheme = "agtps" if use_tls else "agtp"
        print(f"[client] connecting: {scheme}://{host}:{port}", file=sys.stderr)

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
        # Note: do not call shutdown(SHUT_WR) on TLS sockets. It sends a
        # close_notify alert that ends the session before the server can
        # respond. Content-Length framing handles request boundaries.
        reader = sock.makefile("rb")
        return wire.parse_response(reader)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def render_response(response: wire.AGTPResponse, accept: str) -> str:
    """Format the response body for terminal display."""
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


def open_in_browser(html: str, agent_id: str) -> Path:
    """
    Write HTML to a temp file and open it in the user's default browser.
    Returns the path written.
    """
    short = agent_id[:12]
    tmpdir = Path(tempfile.gettempdir())
    out_path = tmpdir / f"agtp-{short}.html"
    out_path.write_text(html, encoding="utf-8")
    webbrowser.open(out_path.as_uri())
    return out_path


def run(args) -> int:
    try:
        parsed = parse_uri(args.uri)
    except AgentIDError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # Determine output format from the mutually exclusive flags.
    if args.yaml:
        accept = CONTENT_TYPE_YAML
        fmt = "yaml"
    elif args.html:
        accept = CONTENT_TYPE_HTML
        fmt = "html"
    else:
        # Default: JSON to stdout. Easiest to compose with other tools.
        accept = CONTENT_TYPE_JSON
        fmt = "json"

    try:
        host, port = resolve_target(parsed, args.registry, verbose=args.verbose)
    except ResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    try:
        response = fetch_agent_document(
            parsed.agent_id,
            host,
            port,
            accept,
            use_tls=not args.insecure,
            insecure_skip_verify=args.insecure_skip_verify,
            verbose=args.verbose,
        )
    except (OSError, wire.WireFormatError) as exc:
        print(f"error: connection failed: {exc}", file=sys.stderr)
        return 1

    body = render_response(response, accept)

    # HTML: open in browser unless --no-open was passed.
    if fmt == "html" and not args.no_open and response.status_code == 200:
        path = open_in_browser(body, parsed.agent_id)
        if args.verbose:
            print(f"[client] opened {path}", file=sys.stderr)
        return 0

    # All other cases: print to stdout.
    print(body)
    return 0 if response.status_code == 200 else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="agtp",
        description="AGTP client — resolves agtp:// URIs",
        epilog=(
            "Examples:\n"
            "  agtp agtp://d8dc6f0d...\n"
            "  agtp agtp://d8dc6f0d... --html\n"
            "  agtp agtp://d8dc6f0d... --yaml\n"
            "  agtp agtp://d8dc6f0d...@agents.agtp.io"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("uri", help="agtp:// URI to resolve")

    fmt_group = parser.add_mutually_exclusive_group()
    fmt_group.add_argument(
        "--json", action="store_true", help="JSON output (default)"
    )
    fmt_group.add_argument(
        "--yaml", action="store_true", help="YAML output"
    )
    fmt_group.add_argument(
        "--html",
        action="store_true",
        help="HTML identity card, opens in default browser",
    )

    parser.add_argument(
        "--no-open",
        action="store_true",
        help="With --html: print HTML to stdout instead of opening browser",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Show resolution and connection steps on stderr",
    )

    parser.add_argument(
        "--registry",
        default=DEFAULT_REGISTRY_URL,
        help=argparse.SUPPRESS,  # hidden — testing only
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help=argparse.SUPPRESS,  # hidden — development only
    )
    parser.add_argument(
        "--insecure-skip-verify",
        action="store_true",
        help=argparse.SUPPRESS,  # hidden — development only
    )

    return run(parser.parse_args())


if __name__ == "__main__":
    sys.exit(main())
