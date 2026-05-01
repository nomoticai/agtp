"""
AGTP client wrapper.

Refactored from agtp.py for use as a library by the Ovoara browser. The
fetch() entry point returns a structured dict so the UI can render
success and failure uniformly.
"""

from __future__ import annotations

import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

# AGTP v1 reference library lives outside this project. Allow override via
# AGTP_LIB_PATH env var; otherwise try two common layouts:
#   1. elemen is a subdirectory of the agtp repo  -> ../v1
#   2. elemen is a sibling of the agtp repo       -> ../agtp/v1
_DEFAULT_LIB_CANDIDATES = [
    Path(os.environ.get("AGTP_LIB_PATH", "")),
    Path(__file__).resolve().parent.parent / "v1",
    Path(__file__).resolve().parent.parent / "agtp" / "v1",
]

for _candidate in _DEFAULT_LIB_CANDIDATES:
    if _candidate and _candidate.is_dir() and (_candidate / "wire_v2.py").exists():
        sys.path.insert(0, str(_candidate))
        break
else:
    raise RuntimeError(
        "Could not locate AGTP v1 library (agent_id.py, agent_document.py, "
        "wire_v2.py). Set AGTP_LIB_PATH env var to its directory."
    )

from agent_id import parse_uri, ParsedURI, AgentIDError  # noqa: E402
from agent_document import (  # noqa: E402
    CONTENT_TYPE_HTML,
    CONTENT_TYPE_JSON,
    CONTENT_TYPE_YAML,
)
import wire_v2 as wire  # noqa: E402


DEFAULT_REGISTRY_URL = "https://registry.agtp.io"

FORMAT_TO_ACCEPT = {
    "json": CONTENT_TYPE_JSON,
    "yaml": CONTENT_TYPE_YAML,
    "html": CONTENT_TYPE_HTML,
}


class ResolutionError(Exception):
    pass


def lookup_registry(agent_id: str, registry_url: str) -> tuple[str, int]:
    url = f"{registry_url.rstrip('/')}/registry/{agent_id}"
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


def resolve_target(parsed: ParsedURI, registry_url: str) -> tuple[str, int]:
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
        # Don't half-close on TLS sockets — close_notify ends the session.
        reader = sock.makefile("rb")
        return wire.parse_response(reader)
    finally:
        try:
            sock.close()
        except OSError:
            pass


def fetch(
    uri: str,
    fmt: str = "json",
    registry: str = DEFAULT_REGISTRY_URL,
    *,
    insecure: bool = False,
    insecure_skip_verify: bool = False,
) -> dict:
    """
    Resolve an agtp:// URI and return a result dict for UI rendering.

    Result shape:
        ok=True:  {ok, agent_id, host, port, status_code, status_text,
                   headers, body, content_type, format}
        ok=False: {ok, error, stage}
    """
    try:
        parsed = parse_uri(uri)
    except AgentIDError as exc:
        return {"ok": False, "error": str(exc), "stage": "parse"}

    accept = FORMAT_TO_ACCEPT.get(fmt, CONTENT_TYPE_JSON)

    try:
        host, port = resolve_target(parsed, registry)
    except ResolutionError as exc:
        return {
            "ok": False,
            "error": str(exc),
            "stage": "resolve",
            "agent_id": parsed.agent_id,
        }

    try:
        response = fetch_agent_document(
            parsed.agent_id,
            host,
            port,
            accept,
            use_tls=not insecure,
            insecure_skip_verify=insecure_skip_verify,
        )
    except (OSError, wire.WireFormatError) as exc:
        return {
            "ok": False,
            "error": f"connection failed: {exc}",
            "stage": "fetch",
            "agent_id": parsed.agent_id,
            "host": host,
            "port": port,
        }

    body = response.body_bytes.decode("utf-8", errors="replace")

    return {
        "ok": True,
        "agent_id": parsed.agent_id,
        "host": host,
        "port": port,
        "status_code": response.status_code,
        "status_text": response.status_text,
        "headers": dict(response.headers),
        "body": body,
        "content_type": response.headers.get("Content-Type", ""),
        "format": fmt,
    }
