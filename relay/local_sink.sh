#!/usr/bin/env bash
# Fallback receiver ON THE LAPTOP
set -euo pipefail
cd "$(dirname "$0")/.."
source config/experiment.env
mkdir -p data/laptop_sink
python3 sink/sink.py --host 0.0.0.0 --port "${LOCAL_SINK_PORT}" --log data/laptop_sink/sink_log.jsonl
