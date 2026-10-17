# This module provides functions to communicate with the power server running on the host machine, 
# allowing the Pi to start and stop power captures, fetch power traces, and synchronize its clock with the host clock.
import json
import socket
import time

import gw_config as cfg

BASE = time.time() - time.monotonic()

# Pi's clock in seconds since the epoch, monotonic if mono=True.
def pi_clock(mono=None):
    return (time.monotonic() if mono is None else mono) + BASE

# Request/response to the power server. The request is a JSON object with a "cmd" key and optional arguments. 
# The response is a JSON object with an "ok" key and optional data. 
# If raw=True, the response is a tuple of (head, data) where head is the JSON object and data is the raw bytes of the trace. 
# The timeout is in seconds.
def _request(obj, timeout=180, raw=False):
    with socket.create_connection((cfg.POWER_HOST, cfg.POWER_PORT), timeout=timeout) as s:
        s.sendall((json.dumps(obj) + "\n").encode())
        f = s.makefile("rb")
        head = json.loads(f.readline())

        if raw and head.get("ok"):
            return head, f.read(head["bytes"])
        
        return head

# Sync the Pi clock with the host clock. Returns a dict with keys:
#   offset_s: host - pi offset in seconds
#   rtt_s: round-trip time in seconds
#   t_pi: pi clock at the midpoint of the exchange
def sync(n=15):
    best = None

    for _ in range(n):
        t1 = pi_clock()
        t_host = _request({"cmd": "sync"}, timeout=5)["t_host"]
        t3 = pi_clock()
        rtt = t3 - t1

        if best is None or rtt < best["rtt_s"]:
            best = {"offset_s": t_host - (t1 + t3) / 2, "rtt_s": rtt, "t_pi": (t1 + t3) / 2}

        time.sleep(0.02)

    return best

# Start a power capture on the host. Returns a dict with keys:
#   ok: True if the capture started successfully
#   run_id: the unique identifier for the capture
def start(run_id):
    r = _request({"cmd": "start", "run_id": run_id})

    if not r.get("ok"):
        raise RuntimeError(f"power capture start failed: {r}")
    
    return r

# Stop a power capture on the host. Returns a dict with keys:
#   ok: True if the capture stopped successfully
#   run_id: the unique identifier for the capture
def stop(run_id):
    return _request({"cmd": "stop", "run_id": run_id})

# Fetch the power trace from the host. Writes the raw bytes to dest and returns the number of bytes written.
def fetch_trace(run_id, dest):
    head = _request({"cmd": "trace", "run_id": run_id}, raw=True)

    if isinstance(head, dict):
        raise RuntimeError(f"trace not available: {head}")
    _, data = head

    with open(dest, "wb") as f:
        f.write(data)

    return len(data)
