# This script computes the energy consumed by the Pi during each GL2 connection, based on the power trace and the timestamps of the first byte and EOF of each connection. 
import argparse
import json

import numpy as np
import pandas as pd

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--eb", required=True)
    ap.add_argument("--sink-log", required=True)
    ap.add_argument("--runs", required=True, nargs="+")
    ap.add_argument("--out", default="data/results/gl2_energy.csv")
    a = ap.parse_args()

    eb = pd.read_csv(a.eb)
    t = eb["Time"].astype(float) / 1000.0
    ecols = [c for c in eb.columns if "ENERGY" in c.upper()]

    if not ecols:
        raise SystemExit(f"No *ENERGY* columns in {a.eb}: {list(eb.columns)}")
    
    inc = eb[ecols].astype(float).diff().clip(lower=0).fillna(0).sum(axis=1).to_numpy()
    cum, tt = np.cumsum(inc), t.to_numpy()
    energy = lambda a, b: float(np.interp(b, tt, cum) - np.interp(a, tt, cum))

    sink = pd.DataFrame([json.loads(line) for line in open(a.sink_log)])
    rows = []

    for _, c in sink.iterrows():
        start = c.t_first_byte if pd.notna(c.t_first_byte) else c.t_accept
        dur = c.t_eof - start
        e = energy(start, c.t_eof)
        rows.append({"sink_conn_id": c.conn_id, "gl2_bytes": c.bytes, "gl2_seconds": dur,
                     "gl2_energy_j": e, "gl2_mean_power_w": e / dur if dur > 0 else np.nan})
        
    per_conn = pd.DataFrame(rows)

    runs = pd.concat([pd.read_csv(p) for p in a.runs], ignore_index=True)
    runs = runs[runs["__done"] == "DONE"].copy()

    runs["sink_conn_id"] = pd.to_numeric(runs["sink_conn_id"], errors="coerce")
    per_conn["sink_conn_id"] = per_conn["sink_conn_id"].astype(float)

    merged = runs[["__run_id", "treatment", "payload", "sink_conn_id", "valid"]].merge(
        per_conn, on="sink_conn_id", how="left")
    merged.to_csv(a.out, index=False)

    print(merged.groupby(["treatment", "payload"])[["gl2_energy_j", "gl2_seconds"]].mean().round(2))
    print(f"saved {a.out}")

if __name__ == "__main__":
    main()
