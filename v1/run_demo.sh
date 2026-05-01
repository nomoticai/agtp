#!/usr/bin/env bash
# AGTP v1 demo runner.
#
# Starts the registry on localhost:8080 (HTTP, dev mode), starts the
# agent server on localhost:4480 (plaintext, dev mode), registers Lauren
# with the registry, and runs the client through three scenarios:
#
#   1. agtp://{lauren-id}                 -> JSON (default)
#   2. agtp://{lauren-id}?format=yaml     -> YAML
#   3. agtp://{lauren-id}?format=html     -> HTML identity card
#
# All output is captured to transcripts/demo-output.txt.
#
# Usage:
#   ./run_demo.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p transcripts
TRANSCRIPT="transcripts/demo-output.txt"
: > "$TRANSCRIPT"

LAUREN_ID=$(cat LAUREN_AGENT_ID)

echo "==================================================================" | tee -a "$TRANSCRIPT"
echo "AGTP v1 Demo"                                                       | tee -a "$TRANSCRIPT"
echo "Run at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"                             | tee -a "$TRANSCRIPT"
echo "Agent: Lauren"                                                      | tee -a "$TRANSCRIPT"
echo "ID:    $LAUREN_ID"                                                  | tee -a "$TRANSCRIPT"
echo "==================================================================" | tee -a "$TRANSCRIPT"

cleanup() {
    if [ -n "${REGISTRY_PID:-}" ] && kill -0 "$REGISTRY_PID" 2>/dev/null; then
        kill "$REGISTRY_PID" 2>/dev/null || true
        wait "$REGISTRY_PID" 2>/dev/null || true
    fi
    if [ -n "${SERVER_PID:-}" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
        kill "$SERVER_PID" 2>/dev/null || true
        wait "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

# Reset registry state so each run is reproducible.
rm -f registry/registry_data.json

echo                                                                      | tee -a "$TRANSCRIPT"
echo "[runner] starting registry on http://127.0.0.1:8080"                | tee -a "$TRANSCRIPT"
python3 registry/registry_server.py \
    --host 127.0.0.1 --port 8080 \
    --store registry/registry_data.json \
    >> transcripts/registry.log 2>&1 &
REGISTRY_PID=$!
sleep 0.4

echo "[runner] registering Lauren -> 127.0.0.1:4480"                      | tee -a "$TRANSCRIPT"
python3 -c "
import sys
sys.path.insert(0, '.')
from registry.registry_server import RegistryStore
from pathlib import Path
store = RegistryStore(Path('registry/registry_data.json'))
store.register('$LAUREN_ID', '127.0.0.1', 4480)
print(f'[runner] registry now contains: {store.list_all()}')
" | tee -a "$TRANSCRIPT"

echo "[runner] starting agent server on agtp://127.0.0.1:4480 (plaintext)" | tee -a "$TRANSCRIPT"
python3 server/agent_server.py \
    --host 127.0.0.1 --port 4480 \
    --agents-dir server/agents \
    --insecure \
    >> transcripts/server.log 2>&1 &
SERVER_PID=$!
sleep 0.4

echo                                                                      | tee -a "$TRANSCRIPT"
echo "==================================================================" | tee -a "$TRANSCRIPT"
echo "SCENARIO 1 — agtp://{lauren-id} as JSON (default)"                  | tee -a "$TRANSCRIPT"
echo "==================================================================" | tee -a "$TRANSCRIPT"
python3 client/agtp.py resolve \
    "agtp://$LAUREN_ID" \
    --format=json \
    --registry http://127.0.0.1:8080 \
    --insecure --insecure-skip-verify \
    2>&1 | tee -a "$TRANSCRIPT"

echo                                                                      | tee -a "$TRANSCRIPT"
echo "==================================================================" | tee -a "$TRANSCRIPT"
echo "SCENARIO 2 — agtp://{lauren-id} as YAML"                            | tee -a "$TRANSCRIPT"
echo "==================================================================" | tee -a "$TRANSCRIPT"
python3 client/agtp.py resolve \
    "agtp://$LAUREN_ID" \
    --format=yaml \
    --registry http://127.0.0.1:8080 \
    --insecure --insecure-skip-verify \
    2>&1 | tee -a "$TRANSCRIPT"

echo                                                                      | tee -a "$TRANSCRIPT"
echo "==================================================================" | tee -a "$TRANSCRIPT"
echo "SCENARIO 3 — agtp://{lauren-id} as HTML"                            | tee -a "$TRANSCRIPT"
echo "==================================================================" | tee -a "$TRANSCRIPT"
echo "(HTML body is captured to transcripts/lauren.html for browser viewing)" | tee -a "$TRANSCRIPT"
python3 client/agtp.py resolve \
    "agtp://$LAUREN_ID" \
    --format=html \
    --registry http://127.0.0.1:8080 \
    --insecure --insecure-skip-verify \
    > transcripts/lauren.html 2>>"$TRANSCRIPT"

echo "(first 30 lines of the HTML output:)"                               | tee -a "$TRANSCRIPT"
head -30 transcripts/lauren.html                                          | tee -a "$TRANSCRIPT"
echo "..."                                                                | tee -a "$TRANSCRIPT"

echo                                                                      | tee -a "$TRANSCRIPT"
echo "==================================================================" | tee -a "$TRANSCRIPT"
echo "SCENARIO 4 — direct host form (bypasses registry)"                  | tee -a "$TRANSCRIPT"
echo "==================================================================" | tee -a "$TRANSCRIPT"
python3 client/agtp.py resolve \
    "agtp://$LAUREN_ID@127.0.0.1:4480" \
    --format=json \
    --registry http://127.0.0.1:8080 \
    --insecure --insecure-skip-verify \
    2>&1 | tee -a "$TRANSCRIPT"

echo                                                                      | tee -a "$TRANSCRIPT"
echo "==================================================================" | tee -a "$TRANSCRIPT"
echo "Demo complete."                                                     | tee -a "$TRANSCRIPT"
echo "Transcript:    $TRANSCRIPT"                                         | tee -a "$TRANSCRIPT"
echo "HTML output:   transcripts/lauren.html"                             | tee -a "$TRANSCRIPT"
echo "Server log:    transcripts/server.log"                              | tee -a "$TRANSCRIPT"
echo "Registry log:  transcripts/registry.log"                            | tee -a "$TRANSCRIPT"
