#!/usr/bin/env python3
import subprocess
import sys
import time

from _common import REPO, Capture, OUT

W = float(sys.argv[1]) if len(sys.argv) > 1 else 120
REPS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
rows = []

# Measure the overhead of the sampler.py process on the Pi's power consumption.
with Capture("sampler_overhead") as c:
    time.sleep(30)      

    for k in range(REPS):
        c.mark(f"a{k}0"); time.sleep(W); c.mark(f"a{k}1")
        sp = subprocess.Popen([sys.executable, str(REPO / "experiment" / "sampler.py"),
                               "--out", str(OUT / f"sampler_overhead_samples_{k}.csv")])
        
        time.sleep(2)
        c.mark(f"b{k}0"); time.sleep(W); c.mark(f"b{k}1")
        sp.terminate(); sp.wait()
        time.sleep(10)

for k in range(REPS):
    pa, ca = c.mean_power(f"a{k}0", f"a{k}1")
    pb, cb = c.mean_power(f"b{k}0", f"b{k}1")
    rows.append((k, pa, pb, pb - pa, min(ca, cb)))

    print(f"rep {k}: idle {pa:.4f} W | idle+sampler {pb:.4f} W | overhead {pb - pa:+.4f} W (coverage {min(ca, cb):.3f})")

mean = sum(r[3] for r in rows) / len(rows)

print(f"mean sampler overhead: {mean:+.4f} W  -> report this in Section 5.2")

(OUT / "sampler_overhead.csv").write_text("rep,idle_w,idle_sampler_w,overhead_w,coverage\n" +
                                          "\n".join(",".join(f"{x}" for x in r) for r in rows) + "\n")
