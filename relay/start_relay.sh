#!/usr/bin/env bash
# Forward's the laptop:SINK_PORT to gl2 (127.0.0.1:SINK_PORT), so the Pi can reach it through the access point:
set -euo pipefail
cd "$(dirname "$0")/.."
source config/experiment.env

FWD="0.0.0.0:${LOCAL_SINK_PORT}:127.0.0.1:${SINK_PORT}"
OPTS=(-N -g -L "$FWD" -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=4)

if [[ -n "${GL2_SSH_ALIAS:-}" ]]; then
  TARGET=("$GL2_SSH_ALIAS")
else
  [[ -n "$JUMP_HOST" ]] || { echo "Set JUMP_HOST/JUMP_USER in config/experiment.env"; exit 1; }
  TARGET=(-i "${SSH_KEY/#\~/$HOME}" -J "${JUMP_USER}@${JUMP_HOST}" "${GL2_USER}@${GL2_HOST}")
fi

echo "Relay: Pi -> $(hostname):${LOCAL_SINK_PORT} -> gl2:127.0.0.1:${SINK_PORT}  (Ctrl-C to stop)"
# macOS: allow incoming connections for ssh if the firewall asks.
while true; do
  ssh "${OPTS[@]}" "${TARGET[@]}" || true
  echo "$(date) relay dropped - reconnecting in 5s"
  sleep 5
done
