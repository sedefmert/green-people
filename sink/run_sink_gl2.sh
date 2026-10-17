#!/usr/bin/env bash
# Start the receiver on gl2 inside tmux
#   window "sink" : sink.py on 127.0.0.1:$SINK_PORT (reached through the laptop relay)
#   window "eb"   : EnergiBridge for the whole session
# Layout on gl2:  ~/config/experiment.env   ~/sink/sink.py   ~/sink/run_sink_gl2.sh
# Usage: bash ~/sink/run_sink_gl2.sh [session_hours]
# Stop : tmux kill-session -t gw_sink

set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
[[ -f config/experiment.env ]] || { echo "missing $ROOT/config/experiment.env"; exit 1; }
[[ -f sink/sink.py ]]          || { echo "missing $ROOT/sink/sink.py"; exit 1; }
source config/experiment.env
HOURS="${1:-10}"
OUT="$HOME/${GL2_OUT_DIR}"
STAMP="$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUT"

command -v energibridge >/dev/null || { echo "energibridge not on PATH"; exit 1; }
command -v tmux >/dev/null         || { echo "tmux not installed"; exit 1; }
tmux has-session -t gw_sink 2>/dev/null && { echo "tmux session gw_sink already running"; exit 1; }

tmux new-session -d -s gw_sink -n sink -c "$ROOT"
tmux send-keys -t gw_sink:sink \
  "python3 sink/sink.py --host 127.0.0.1 --port ${SINK_PORT} --log ${OUT}/sink_log.jsonl 2>&1 | tee -a ${OUT}/sink_console_${STAMP}.log" C-m
tmux new-window -t gw_sink -n eb -c "$ROOT"
tmux send-keys -t gw_sink:eb \
  "energibridge --output ${OUT}/energibridge_${STAMP}.csv --summary -- sleep $((HOURS*3600)) 2>&1 | tee ${OUT}/energibridge_summary_${STAMP}.txt" C-m

{ echo "started_utc=$(date -u +%FT%TZ)"; echo "host=$(hostname)"; lscpu | head -20; \
  energibridge --version 2>/dev/null || true; python3 --version; } > "${OUT}/gl2_env_${STAMP}.txt"

sleep 2
if nc -z 127.0.0.1 "${SINK_PORT}" 2>/dev/null || ss -ltn | grep -q ":${SINK_PORT} "; then
  echo "Sink listening on 127.0.0.1:${SINK_PORT}, EnergiBridge running. Logs in ${OUT}"
else
  echo "Sink failed with error: see the error with: tmux attach -t gw_sink"
fi
echo "Attach: tmux attach -t gw_sink, Detach: Ctrl-b d"
