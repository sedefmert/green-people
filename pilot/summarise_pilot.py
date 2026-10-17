#!/usr/bin/env python3
import sys

import pandas as pd

IDLE_S, COOLDOWN_S, OVERHEAD_S, REPS = 60, 120, 8, 10
TREATMENTS = ["none", "zip", "tar.gz", "tar.zst", "tar.br"]

# Summarise the pilot/warm-up runs, and estimate the main session length.
def main(paths):
    df = pd.concat([pd.read_csv(p).assign(source=p) for p in paths], ignore_index=True)
    df = df[df["__done"] == "DONE"]
    cols = ["t_compress_s", "t_transmit_s", "energy_total_j", "compression_ratio", "wlan_tx_mb"]
    print("== per cell")
    print(df.groupby(["treatment", "payload"])[cols].mean().round(2))
    print("\n== validity")
    print(df.groupby(["treatment", "payload"])["valid"].agg(["count", "sum"]))
    bad = df[df["valid"] != True]  # noqa: E712
    if len(bad):
        print("\nINVALID runs:\n", bad[["__run_id", "treatment", "payload", "invalid_reason"]])

    work = df.groupby(["treatment", "payload"])[["t_compress_s", "t_transmit_s"]].mean().sum(axis=1)
    total, missing = 0.0, []
    for t in TREATMENTS:
        for p in ["S", "L"]:
            if (t, p) in work:
                w = work[(t, p)]
            elif (t, "L") in work and p == "S":     # scale L -> S by payload size
                w = work[(t, "L")] * (df[df.payload == "S"].payload_bytes.mean()
                                      / df[df.payload == "L"].payload_bytes.mean())
                missing.append(f"{t}/S (scaled from L)")
            else:
                missing.append(f"{t}/{p} (unknown)")
                continue
            total += REPS * (IDLE_S + w + OVERHEAD_S + COOLDOWN_S)
    print(f"\n== estimated main session: {total/3600:.1f} h for {len(TREATMENTS)*2*REPS} runs"
          f" (+ re-executions)")
    print("   slowest cell:", work.idxmax(), f"{work.max():.0f} s of work per run")
    if missing:
        print("   estimated without direct pilot data:", ", ".join(missing))


if __name__ == "__main__":
    main(sys.argv[1:])
