#!/usr/bin/env bash
# Start an Experiment Runner session on the Pi (inside tmux, so an SSH drop does not kill it).
#   bash experiment/run.sh [<mode>] (pilot | warmup | main | rerun)
#   bash experiment/run.sh rerun experiment/experiments/greenwarriors_main/run_table.csv
# Re-running the same command after an interruption resumes at the first TODO row.
set -euo pipefail
cd "$(dirname "$0")"
MODE="${1:?mode: pilot|warmup|main|rerun}"
export GW_MODE="$MODE"
if [[ "$MODE" == rerun ]]; then export GW_RERUN_SOURCE="$(realpath "${2:?path to run_table.csv}")"; fi
[[ "$MODE" == main || "$MODE" == rerun ]] || export GW_SKIP_VERIFY="${GW_SKIP_VERIFY:-0}"
PY="${PY:-$HOME/gw-venv/bin/python}"
ER="${ER:-$HOME/experiment-runner/experiment-runner/}"
exec "$PY" "$ER" "$(pwd)/RunnerConfig.py"
