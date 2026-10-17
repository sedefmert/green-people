#!/usr/bin/env bash
# This script measures throughput to the relay and local sink, saving results to a CSV file.
set -euo pipefail
cd "$(dirname "$0")/.."
source config/experiment.env
SIZE_MB="${1:-300}"
mkdir -p data/pilot
OUT="data/pilot/throughput_$(date +%Y%m%d_%H%M%S).csv"
echo "target,port,trial,bytes,seconds,mbit_s,sink_reply" > "$OUT"
for target in "relay:${SINK_PORT}" "laptop:${LOCAL_SINK_PORT}"; do
  port="${target#*:}"
  for trial in 1 2 3; do
    t0=$(date +%s.%N)
    reply=$(head -c "$((SIZE_MB*1000000))" /dev/zero | nc -N "$SINK_HOST" "$port" || true)
    t1=$(date +%s.%N)
    secs=$(echo "$t1 - $t0" | bc -l)
    mbit=$(echo "$SIZE_MB*8/$secs" | bc -l)
    printf "%s,%s,%d,%d,%.3f,%.1f,%s\n" "${target%%:*}" "$port" "$trial" "$((SIZE_MB*1000000))" "$secs" "$mbit" "$reply" | tee -a "$OUT"
    sleep 5
  done
done
echo "Saved $OUT. If relay is clearly slower than laptop, use the local sink (README step 9c)."
