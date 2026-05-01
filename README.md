# AGTP v1 Reference Implementation

The first running implementation of the Agent Transfer Protocol identity
model. Resolves `agtp://{agent-id}` URIs end-to-end, returns Agent
Documents in JSON, YAML, or HTML.

The first agent registered is **Lauren** —
`agtp://d8dc6f0df55d66c7b30100db3cffbe383c5f814e6e58a08521fb7636c3bcc230`.

## What this proves

- Canonical AGTP URIs (Form 1 from v06) resolve to a serving host:port
  via a registry lookup, and Form 1a (`agent-id@host`) bypasses the
  registry directly.
- Agent Documents in `application/agent+json` carry the eleven-field v1
  identity schema.
- Content negotiation produces JSON, YAML, or a rendered HTML identity
  card from the same URI based on the client's `Accept` header.
- DESCRIBE method serves Agent Documents over AGTP wire format on
  port 4480.

## Components

```
agtp-v1/
├── agent_id.py          ID generation, URI parsing
├── agent_document.py    11-field schema, JSON/YAML serializers
├── renderer.py          HTML identity card renderer
├── wire_v2.py           AGTP wire format (request/response framing)
├── server/
│   ├── agent_server.py  Hosts agents, serves on port 4480
│   └── agents/
│       └── lauren.agent.json
├── registry/
│   └── registry_server.py   Resolves agent IDs to host:port
├── client/
│   └── agtp.py          CLI client: `agtp resolve agtp://...`
├── run_demo.sh          End-to-end demo runner
└── transcripts/         Captured outputs
```

## Local demo

```
./run_demo.sh
```

Starts the registry on `127.0.0.1:8080`, registers Lauren, starts the
agent server on `127.0.0.1:4480`, then runs four scenarios:

1. `agtp://{lauren-id}` → JSON
2. `agtp://{lauren-id}` → YAML
3. `agtp://{lauren-id}` → HTML (saved to `transcripts/lauren.html`)
4. `agtp://{lauren-id}@127.0.0.1:4480` → JSON (direct host form, no
   registry)

## Public deployment

The pieces below are what's needed to take this from loopback to the
public Internet. Each is a deployment task, not a code change — the
implementation itself is ready.

### 1. Domain and DNS

Two A records:

```
agtp.nomotic.ai      → registry server IP
agents.nomotic.ai    → agent server IP   (or same IP, different ports)
```

### 2. TLS certificates

Let's Encrypt via certbot, one cert per hostname.

```
certbot certonly --standalone -d agtp.nomotic.ai
certbot certonly --standalone -d agents.nomotic.ai
```

### 3. Firewall

```
ufw allow 443/tcp     # registry HTTPS
ufw allow 4480/tcp    # agent server AGTP+TLS
```

### 4. Run the registry

```
python3 registry/registry_server.py \
    --host 0.0.0.0 --port 443 \
    --cert /etc/letsencrypt/live/agtp.nomotic.ai/fullchain.pem \
    --key  /etc/letsencrypt/live/agtp.nomotic.ai/privkey.pem
```

Or front it with nginx/Caddy on 443 and run the registry on a higher
port behind the proxy.

### 5. Register Lauren against the public agent host

```
python3 -c "
from registry.registry_server import RegistryStore
from pathlib import Path
RegistryStore(Path('registry/registry_data.json')).register(
    'd8dc6f0df55d66c7b30100db3cffbe383c5f814e6e58a08521fb7636c3bcc230',
    'agents.nomotic.ai',
    4480,
)
"
```

### 6. Run the agent server

```
python3 server/agent_server.py \
    --host 0.0.0.0 --port 4480 \
    --agents-dir server/agents \
    --cert /etc/letsencrypt/live/agents.nomotic.ai/fullchain.pem \
    --key  /etc/letsencrypt/live/agents.nomotic.ai/privkey.pem
```

### 7. Resolve from anywhere

```
python3 client/agtp.py resolve agtp://d8dc6f0d...c3bcc230 --format=html
```

The default registry URL is `https://agtp.nomotic.ai`. Override with
`--registry` for testing alternative registries.

## Lauren's agent document

```
agtp_version:    1.0
agent_id:        d8dc6f0df55d66c7b30100db3cffbe383c5f814e6e58a08521fb7636c3bcc230
name:            Lauren
principal:       Chris Hood
principal_id:    principal-chris-hood-001
description:     The first AGTP-identified agent.
status:          active
capabilities:    [DESCRIBE]
scopes_accepted: [identity:read, capability:read]
issued_at:       (set at generation)
issuer:          agtp.nomotic.ai
```

## What's not in v1

Deliberate scope cuts, listed for the v07 / v2 backlog:

- **Cryptographic signatures.** The Agent Document is currently
  unsigned. v06 references Birth Certificate hashes as the basis for
  Agent IDs; v2 wires this in.
- **Trust scores.** Mentioned in v06 but not yet computed or surfaced
  in the document.
- **Public registration UI.** `https://agtp.nomotic.ai/register`
  becomes the front door to AGTP for non-technical adopters in v2.
- **AGTP-CERT integration.** The `agent.cert` companion file format.
- **Methods beyond DESCRIBE.** QUERY, BOOK, DELEGATE etc. require their
  scope-enforcement model (already prototyped in the earlier demo) plus
  the per-agent capability bindings.
- **`.well-known/agtp` bootstrap.** The fallback that lets domains with
  no AGTP infrastructure declare their AGTP namespace via a static file.
- **Federated registries.** v1 hardcodes one registry; v2 supports
  multiple and resolves across them.
