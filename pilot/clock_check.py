#!/usr/bin/env python3
# Check that the Pi's CPU load is reflected in the Shelly plug's power readings, and measure the lag between them.
import multiprocessing as mp
import statistics
import sys
import time

from _common import Capture, OUT, cfg

N = int(sys.argv[1]) if len(sys.argv) > 1 else 8
BURST_S = float(sys.argv[2]) if len(sys.argv) > 2 else 5.0
GAP_S = max(3.0, 1.6 * BURST_S)

# spin CPU cores to generate load, while the Shelly plug is polled in the background. 
# The Pi's monotonic clock is marked at the start and end of each burst, 
# and the power trace is analyzed to find the rising/falling edges of the power step. 
# The residuals between the expected and measured edges are reported, and a new POWER_LAG_S value is suggested if needed.
def spin(go, quit_):
    while not quit_.is_set():
        if go.wait(0.5):
            while go.is_set():
                pass

if __name__ == "__main__":
    go, quit_ = mp.Event(), mp.Event()
    workers = [mp.Process(target=spin, args=(go, quit_)) for _ in range(mp.cpu_count())]

    for w in workers:
        w.start()

    with Capture("clock_check") as c:
        time.sleep(10)

        for k in range(N):
            c.mark(f"up{k}"); go.set()
            time.sleep(BURST_S)
            go.clear(); c.mark(f"down{k}")
            time.sleep(GAP_S)

        time.sleep(2)

    quit_.set()

    for w in workers:
        w.join()

    blocks = c.blocks

    t = [b[1] for b in blocks]
    p = [b[2] for b in blocks]

    first = c.to_host(c.marks["up0"])

    idle = statistics.median(pi for ti, pi in zip(t, p) if ti < first - 1)
    busy = statistics.median(pi for ti, pi in zip(t, p)
                             if any(c.to_host(c.marks[f"up{k}"]) + 0.4 * BURST_S < ti < c.to_host(c.marks[f"down{k}"]) - 0.1 * BURST_S
                                    for k in range(N)))
    
    thr = (idle + busy) / 2

    if busy - idle < 0.2:
        sys.exit(f"No clear power step (idle {idle:.3f} W, burst {busy:.3f} W): "
                 "check that the Pi is powered through the Shelly plug.")
        
    ups = [t[i] for i in range(1, len(p)) if p[i - 1] <= thr < p[i]]
    downs = [t[i] for i in range(1, len(p)) if p[i - 1] > thr >= p[i]]
    lags = []

    for k in range(N):
        for label, crossings in ((f"up{k}", ups), (f"down{k}", downs)):
            exp = c.to_host(c.marks[label])
            near = [x - exp for x in crossings if -0.5 < x - exp < 0.6 * BURST_S]

            if near:
                lags.append(min(near, key=abs))
    lag = statistics.median(lags)

    print(f"idle {idle:.3f} W, burst {busy:.3f} W, threshold {thr:.3f} W")
    print(f"edge residuals (s): min {min(lags):+.4f}  median {lag:+.4f}  max {max(lags):+.4f}  (n={len(lags)})")
    print(f"clock sync rtt: pre {c.sync_pre['rtt_s']*1000:.1f} ms, post {c.sync_post['rtt_s']*1000:.1f} ms")

    if abs(lag) > 0.05:
        print(f"Set POWER_LAG_S={cfg.POWER_LAG_S + lag:.3f} in config/experiment.env and run the check again")
    else:
        print(f"Residual below 50 ms: keep POWER_LAG_S as is")
        
    (OUT / "clock_check.csv").write_text("edge_residual_s\n" + "\n".join(f"{x:.6f}" for x in lags) + "\n")
