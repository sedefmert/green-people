#!/usr/bin/env python3
# This script samples the Pi's CPU and network counters at a fixed period and writes them to a CSV file. 
# It is intended to be run in the background during an experiment, and it can be stopped by sending SIGTERM or SIGINT. 
# The first sample is taken immediately, and subsequent samples are taken at the specified period. 
# If the sampling falls behind, it resynchronizes instead of bursting.
import argparse
import csv
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import gw_config as cfg  # noqa: E402
import pi_probe as probe  # noqa: E402

stop = False

# Stop the sampling when SIGTERM or SIGINT is received.
def _stop(*_):
    global stop
    stop = True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--period", type=float, default=cfg.SAMPLE_PERIOD_S)
    args = ap.parse_args()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    out = Path(args.out)
    ready = out.with_suffix(".ready")
    samples = []
    t0 = time.monotonic()
    k = 0

    # Take a sample of the Pi's CPU and network counters, and append it to the samples list.
    def take():
        t_mono, t_wall = time.monotonic(), time.time()
        busy, total = probe.read_cpu_jiffies()
        tx = probe.read_tx_bytes()
        samples.append({"t_mono": t_mono, "t_wall": t_wall,
                        "cpu_busy": busy, "cpu_total": total, "tx_bytes": tx})
        return t_mono

    while not stop:
        t_mono = take()
        if len(samples) == 1:
            ready.write_text(str(t_mono))
        k += 1
        delay = t0 + k * args.period - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            t0, k = time.monotonic(), 0
    take() 

    cols = ["t_mono", "t_wall", "cpu_busy", "cpu_total", "tx_bytes"]

    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, restval="")
        w.writeheader()
        w.writerows(samples)
        
    ready.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
