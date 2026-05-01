# AGTP Deployment Guide

This guide walks from "fresh Ubuntu 24.04 LTS VPS" to "AGTP running on
the public Internet" in about an hour of focused work.

## What you'll have at the end

- A registry service at `https://registry.agtp.io` (or your domain)
- An AGTP agent server at `agents.agtp.io:4480` (TLS, AGTP wire format)
- Lauren resolvable via `agtp://{lauren-id}` from any machine on the
  Internet running an AGTP client
- Both services managed by systemd, surviving reboots and crashes
- Automatic certificate renewal via certbot

## Prerequisites

You need:

- A VPS running **Ubuntu 24.04 LTS** with at least 1 vCPU / 1 GB RAM
- A domain you control (e.g., `agtp.io`)
- DNS A records configured for at least:
  - `registry.<your-domain>` → VPS public IP
  - `agents.<your-domain>` → VPS public IP
- Root or sudo access to the VPS
- Email address for Let's Encrypt notifications

The instructions assume `agtp.io` as the example domain. Substitute your
domain everywhere `agtp.io` appears.

## Step 1: System preparation

```bash
# Update packages
apt update && apt upgrade -y

# Install dependencies (all from default Ubuntu repos)
apt install -y python3 python3-pip git certbot ufw

# Verify Python version (need 3.10+)
python3 --version
```

## Step 2: Firewall

```bash
ufw allow 22/tcp comment 'SSH'
ufw allow 80/tcp comment 'certbot HTTP-01 challenge'
ufw allow 443/tcp comment 'registry HTTPS'
ufw allow 4480/tcp comment 'AGTP'
ufw --force enable
ufw status verbose
```

You should see four ALLOW IN rules.

## Step 3: TLS certificates

Issue one certificate per subdomain you'll use. Standalone mode binds
port 80 briefly during validation:

```bash
certbot certonly --standalone --non-interactive --agree-tos \
    --email YOUR@EMAIL --d registry.agtp.io
certbot certonly --standalone --non-interactive --agree-tos \
    --email YOUR@EMAIL --d agents.agtp.io
```

Repeat for any other subdomains you've planned (`register.agtp.io`,
`ca.agtp.io`, etc.).

Verify automatic renewal:

```bash
systemctl list-timers | grep certbot
```

Should show `certbot.timer` scheduled.

## Step 4: Clone the repository

```bash
# Use /opt/agtp as the canonical location
cd /opt
git clone https://github.com/nomoticai/agtp.git
cd agtp

# Verify the v1 implementation files are present
ls v1/
```

You should see `agent_id.py`, `agent_document.py`, `wire_v2.py`,
`renderer.py`, `run_demo.sh`, plus `server/`, `registry/`, `client/`
subdirectories.

## Step 5: Production data location

Production runtime data must live outside the repo. Create the directory:

```bash
mkdir -p /var/lib/agtp
chmod 750 /var/lib/agtp
```

This is where `registry_data.json` and any future runtime state will
live. Backed up separately, never committed.

## Step 6: Register Lauren against the public agent host

Lauren's identity is in the repo (`v1/server/agents/lauren.agent.json`),
but the registry needs to know which host serves her. For a public
deployment, that's `agents.agtp.io` on port 4480:

```bash
LAUREN_ID=$(cat /opt/agtp/v1/LAUREN_AGENT_ID)
cd /opt/agtp/v1

python3 -c "
import sys
sys.path.insert(0, '.')
from registry.registry_server import RegistryStore
from pathlib import Path
store = RegistryStore(Path('/var/lib/agtp/registry_data.json'))
store.register('$LAUREN_ID', 'agents.agtp.io', 4480)
print('Registered:', store.list_all())
"
```

## Step 7: systemd units

Create two service files. Adjust paths if you used something other than
`/opt/agtp` or different cert hostnames.

### /etc/systemd/system/agtp-registry.service

```ini
[Unit]
Description=AGTP Registry Server
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/agtp/v1
ExecStart=/usr/bin/python3 registry/registry_server.py \
    --host 0.0.0.0 --port 443 \
    --store /var/lib/agtp/registry_data.json \
    --cert /etc/letsencrypt/live/registry.agtp.io/fullchain.pem \
    --key /etc/letsencrypt/live/registry.agtp.io/privkey.pem
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

### /etc/systemd/system/agtp-agent.service

```ini
[Unit]
Description=AGTP Agent Server (Lauren)
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/agtp/v1
ExecStart=/usr/bin/python3 server/agent_server.py \
    --host 0.0.0.0 --port 4480 \
    --agents-dir server/agents \
    --cert /etc/letsencrypt/live/agents.agtp.io/fullchain.pem \
    --key /etc/letsencrypt/live/agents.agtp.io/privkey.pem
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

A note on `User=root`: ports below 1024 (specifically 443 in this case)
require either root or a `CAP_NET_BIND_SERVICE` capability grant. For
v1 simplicity we run as root. A future hardening pass moves both
services to a dedicated `agtp` user with capability grants.

Enable and start:

```bash
systemctl daemon-reload
systemctl enable agtp-registry agtp-agent
systemctl start agtp-registry agtp-agent

# Verify
systemctl status agtp-registry
systemctl status agtp-agent
```

Both should show `active (running)`.

## Step 8: Install the deploy script

```bash
ln -sf /opt/agtp/scripts/agtp-deploy.sh /usr/local/bin/agtp-deploy
chmod +x /opt/agtp/scripts/agtp-deploy.sh
```

After this, future deploys are one command:

```bash
agtp-deploy
```

## Step 9: Verification from the public Internet

From any machine other than the VPS:

```bash
# Registry health
curl https://registry.agtp.io/health
# → {"status": "ok"}

# Lauren's registration
curl https://registry.agtp.io/registry/$(cat LAUREN_AGENT_ID)
# → {"agent_id": "...", "host": "agents.agtp.io", "port": 4480}

# Full resolution via the AGTP client
cd /path/to/agtp/v1
python3 client/agtp.py resolve \
    "agtp://$(cat LAUREN_AGENT_ID)" \
    --registry https://registry.agtp.io \
    --format=html
# → Lauren's identity card as HTML
```

If all three work, **AGTP is live on the public Internet.**

## Future deployments

After the initial setup, deploying changes is:

```bash
# On your laptop
git add .
git commit -m "..."
git push

# On the VPS
agtp-deploy
```

That's it.

## Troubleshooting

**`systemctl status agtp-registry` shows "failed".**
Check `journalctl -u agtp-registry -n 50`. Most common causes:

- Port 443 already bound by something else (`ss -tlnp | grep :443`)
- Cert files unreadable (paths or permissions wrong)
- Python import errors (verify the v1 files are present)

**`curl` to the registry hangs.**
Firewall isn't allowing 443. Run `ufw status` and confirm.

**`curl` to the registry fails with TLS errors.**
DNS hasn't propagated, or you issued certs for the wrong hostname.
Run `dig registry.agtp.io` to verify it resolves.

**`agtp-deploy` says "Already at latest commit" but services still
seem broken.**
The deploy script only restarts services when there are new commits.
Force a restart:

```bash
systemctl restart agtp-registry agtp-agent
```

## Hardening checklist (post-v1)

- [ ] Move services to a dedicated `agtp` user with
      `CAP_NET_BIND_SERVICE` instead of running as root
- [ ] Add fail2ban to throttle brute-force connection attempts
- [ ] Enable structured logging (currently goes to journald only)
- [ ] Add monitoring (Prometheus exporter, or simple healthcheck cron)
- [ ] Set up offsite backups of `/var/lib/agtp/`
- [ ] Add nginx as a reverse proxy in front of the registry for
      better TLS termination and rate limiting
