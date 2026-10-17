# This script computes the metrics for one run of the experiment, given the samples, power trace and phase marks.
import csv
import json
import sys
from pathlib import Path

# Compute the metrics for one run, given the samples, power trace and phase marks.
def load_samples(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))

    return [{k: float(v) for k, v in r.items() if v != ""} for r in rows]

# Interpolate a value at a given time.
def _interp(t, v, x):
    if x <= t[0]:
        return v[0]
    
    if x >= t[-1]:
        return v[-1]
    
    lo, hi = 0, len(t) - 1

    while hi - lo > 1:
        mid = (lo + hi) // 2
        lo, hi = (mid, hi) if t[mid] <= x else (lo, mid)

    w = (x - t[lo]) / (t[hi] - t[lo])

    return v[lo] + w * (v[hi] - v[lo])

# Compute the CPU utilisation over a time interval.
def cpu_util(samples, a, b):
    if a is None or b is None or b <= a or len(samples) < 2:
        return None, None
    
    t = [s["t_mono"] for s in samples]
    busy = [s["cpu_busy"] for s in samples]
    tot = [s["cpu_total"] for s in samples]
    d_tot = _interp(t, tot, b) - _interp(t, tot, a)
    mean = 100 * (_interp(t, busy, b) - _interp(t, busy, a)) / d_tot if d_tot > 0 else None
    peak = None

    for prev, cur in zip(samples, samples[1:]):
        if cur["t_mono"] < a or prev["t_mono"] > b:
            continue

        dt = cur["cpu_total"] - prev["cpu_total"]

        if dt > 0:
            u = 100 * (cur["cpu_busy"] - prev["cpu_busy"]) / dt
            peak = u if peak is None else max(peak, u)

    return mean, peak

# Load the power trace from a CSV file.
def load_trace(path, lag_s=0.0):
    with open(path) as f:
        return [(float(r["t0"]) - lag_s, float(r["t1"]) - lag_s, float(r["p_w"]),
                 float(r["energy_counter_j"]) if r.get("energy_counter_j") else None)
                for r in csv.DictReader(f)]

# Compute the energy from the meter's cumulative counter, interpolated at two times.
def counter_energy(blocks, a, b):
    pts = [(t1, c) for _, t1, _, c in blocks if c is not None]

    if len(pts) < 2 or a < pts[0][0] or b > pts[-1][0]:
        return None
    
    t, c = [x[0] for x in pts], [x[1] for x in pts]
    
    return _interp(t, c, b) - _interp(t, c, a)


# Compute the energy and coverage over a time interval, given the power trace.
def block_energy(blocks, a, b):
    e = cov = 0.0

    for t0, t1, p, *_ in blocks:
        if t1 <= a or t0 >= b:
            continue

        dt = min(t1, b) - max(t0, a)
        e += p * dt
        cov += dt

    return e, cov

# Map Pi monotonic time to laptop (power meter) time.
def host_mapper(ph):
    base = ph["clock_base"]
    pre, post = ph["sync_pre"], ph.get("sync_post") or ph["sync_pre"]

    def to_host(mono):
        t = mono + base

        if post["t_pi"] == pre["t_pi"]:
            off = pre["offset_s"]
        else:
            w = (t - pre["t_pi"]) / (post["t_pi"] - pre["t_pi"])
            off = pre["offset_s"] + w * (post["offset_s"] - pre["offset_s"])

        return t + off
    
    return to_host


def compute(samples, blocks, ph, period_s):
    h = host_mapper(ph)

    payload_bytes, expected_baseline = ph["payload_bytes"], ph["expected_baseline_bytes"]
    is_baseline = ph.get("compress_start") is None
    windows = {"idle": (ph["idle_start"] + ph["idle_trim_s"], ph["idle_end"]),
               "transmit": (ph["transmit_start"], ph["transmit_end"])}
    
    if not is_baseline:
        windows["compress"] = (ph["compress_start"], ph["compress_end"])

    energy, coverage = {}, {}
    
    for name, (a, b) in windows.items():
        e, cov = block_energy(blocks, h(a), h(b))
        energy[name], coverage[name] = e, (cov / (b - a) if b > a else 1.0)

    t_idle = windows["idle"][1] - windows["idle"][0]
    p_idle = energy["idle"] / t_idle if t_idle > 0 else None
    e_c = energy.get("compress", 0.0)
    e_tx = energy["transmit"]
    e_total = e_c + e_tx
    t_c = 0.0 if is_baseline else ph["compress_end"] - ph["compress_start"]
    t_tx = ph["transmit_end"] - ph["transmit_start"]

    util_c = (0.0, 0.0) if is_baseline else cpu_util(samples, ph["compress_start"], ph["compress_end"])
    util_tx = cpu_util(samples, ph["transmit_start"], ph["transmit_end"])
    cpu_c = 0.0 if is_baseline else ph["rusage_compress_s"]
    cpu_tx = ph["rusage_transmit_s"]

    sent_bytes = ph["tx_bytes_after"] - ph["tx_bytes_before"]
    archive_bytes = ph.get("archive_bytes")
    expected = expected_baseline if is_baseline else archive_bytes
    ratio = 1.0 if is_baseline else payload_bytes / archive_bytes

    r = {
        # M1
        "cpu_util_mean_compress": util_c[0], "cpu_util_peak_compress": util_c[1],
        "cpu_util_mean_transmit": util_tx[0], "cpu_util_peak_transmit": util_tx[1],
        # M2
        "cpu_time_compress_s": cpu_c, "cpu_time_transmit_s": cpu_tx,
        "cpu_time_total_s": cpu_c + cpu_tx,
        # M3
        "wlan_tx_mb": sent_bytes / 1e6,
        # M4
        "archive_bytes": "" if is_baseline else archive_bytes,
        "compression_ratio": ratio,
        # M5
        "t_compress_s": t_c, "t_transmit_s": t_tx,
        # M6, M7, M8
        "energy_compress_j": e_c, "energy_transmit_j": e_tx, "energy_total_j": e_total,
        "energy_per_mb_j": e_total / (payload_bytes / 1e6),
        # cross-check: meter's cumulative counter over compression + transmission
        "energy_total_counter_j": counter_energy(
            blocks, h(ph["compress_start"] if not is_baseline else ph["transmit_start"]),
            h(ph["transmit_end"])),
        # network energy above idle (Section 5.2) and compression energy above idle
        "energy_tx_above_idle_j": e_tx - (p_idle or 0.0) * t_tx,
        "energy_compress_above_idle_j": 0.0 if is_baseline else e_c - (p_idle or 0.0) * t_c,
        "p_idle_w": p_idle,
        # clock alignment and capture quality
        "clock_offset_pre_s": ph["sync_pre"]["offset_s"],
        "clock_drift_s": (ph.get("sync_post") or ph["sync_pre"])["offset_s"] - ph["sync_pre"]["offset_s"],
        "sync_rtt_max_s": max(ph["sync_pre"]["rtt_s"], (ph.get("sync_post") or ph["sync_pre"])["rtt_s"]),
        "power_max_gap_s": ph.get("power", {}).get("max_gap_s"),
        # validity inputs
        "payload_bytes": payload_bytes,
        "expected_bytes": expected,
        "sink_bytes": ph.get("sink_bytes"),
        "sink_conn_id": ph.get("sink_conn_id"),
    }

    reasons = []
    if ph.get("simulated"):
        reasons.append("simulated")
    if ph.get("compress_rc", 0) != 0:
        reasons.append(f"compress_rc={ph.get('compress_rc')}")
    if ph.get("transmit_rc", 0) != 0:
        reasons.append(f"transmit_rc={ph.get('transmit_rc')}")
    if ph.get("sink_bytes") is None:
        reasons.append("no_sink_reply")
    elif ph["sink_bytes"] != expected:
        reasons.append(f"byte_mismatch({ph['sink_bytes']}!={expected})")
    if expected and sent_bytes < expected:
        reasons.append("wlan_tx_lt_payload")
    if ph.get("throttling_problem"):
        reasons.append("throttling")

    for name, c in coverage.items():
        if c < 0.99:
            reasons.append(f"power_gap_{name}({c:.3f})")

    pw = ph.get("power", {})

    if not pw.get("ok", False):
        reasons.append("power_capture_error")
    else:
        if pw.get("max_gap_s", 0) > 3.0:
            reasons.append(f"power_gap({pw['max_gap_s']:.1f}s)")

    if r["sync_rtt_max_s"] > 0.05:
        reasons.append(f"clock_sync_rtt({r['sync_rtt_max_s']:.3f})")

    span = ph["transmit_end"] - ph["idle_start"]
    n_in = sum(1 for s in samples if ph["idle_start"] <= s["t_mono"] <= ph["transmit_end"])

    if n_in < 0.8 * span / period_s:
        reasons.append(f"too_few_samples({n_in})")

    r["n_samples"] = n_in
    r["bytes_ok"] = ph.get("sink_bytes") == expected
    r["valid"] = not reasons
    r["invalid_reason"] = ";".join(reasons)

    return r


def compute_run_dir(run_dir, period_s=0.2):
    run_dir = Path(run_dir)
    ph = json.loads((run_dir / "phases.json").read_text())
    samples = load_samples(run_dir / "samples.csv")
    blocks = load_trace(run_dir / "power_trace.csv", ph.get("power_lag_s", 0.0))
    
    return compute(samples, blocks, ph, period_s)


if __name__ == "__main__":
    print(json.dumps(compute_run_dir(sys.argv[1]), indent=2))
