#!/usr/bin/env python3
import argparse
import csv
import json
import socketserver
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "experiment"))
import gw_config as cfg

# Shelly smart plug backend to log power and energy consumption of the Pi. The plug is polled over HTTP.
# Runs on team laptop.
class ShellyBackend:
    def __init__(self, host, poll_hz, out_dir=None):
        if not host:
            sys.exit("Set SHELLY_HOST (the plug's IP address) in config/experiment.env")
        self.base, self.period = f"http://{host}", 1.0 / poll_hz
        
        try:
            info = self._get("/rpc/Shelly.GetDeviceInfo")
            self.gen, self.serial = 2, f"{info.get('model')} {info.get('id')} fw {info.get('ver')}"
                
            if out_dir:
                record = {"device_info": info, "recorded_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
                for name, path in (("switch_config", "/rpc/Switch.GetConfig?id=0"),
                                   ("sys_config", "/rpc/Sys.GetConfig")):
                    try:
                        record[name] = self._get(path)

                    except Exception as e:
                        record[name] = f"unavailable: {e}"
                Path(out_dir).mkdir(parents=True, exist_ok=True)
                (Path(out_dir) / "shelly_device.json").write_text(json.dumps(record, indent=2))

        except Exception:
            info = self._get("/shelly")
            self.gen, self.serial = 1, f"{info.get('type')} {info.get('mac')} fw {info.get('fw')}"

        print(f"Shelly Gen{self.gen}: {self.serial}", flush=True)

    def _get(self, path):
        with urllib.request.urlopen(self.base + path, timeout=2) as r:
            return json.loads(r.read())

    def read(self):
        if self.gen >= 2:
            s = self._get("/rpc/Switch.GetStatus?id=0")
            return float(s["apower"]), float(s["aenergy"]["total"]) * 3600.0
        
        s = self._get("/meter/0")
        return float(s["power"]), float(s["total"]) * 60.0

    def capture(self, stop_evt, started_evt):
        samples, errors = [], 0
        k, t0 = 0, time.monotonic()

        while not stop_evt.is_set():
            a = time.time()

            try:
                p, e = self.read()
                samples.append((a + (time.time() - a) / 2, p, e))

                if len(samples) == 2:
                    started_evt.set()

            except Exception:
                errors += 1
            k += 1
            delay = t0 + k * self.period - time.monotonic()

            if delay > 0:
                stop_evt.wait(delay)

        try:
            a = time.time()
            p, e = self.read()
            samples.append((a + (time.time() - a) / 2, p, e))

        except Exception:
            errors += 1
        started_evt.set()
        blocks = [(samples[i - 1][0], samples[i][0], samples[i][1], samples[i][2])
                  for i in range(1, len(samples))]
        
        return blocks, {"poll_errors": errors, "poll_hz": 1 / self.period, "shelly_gen": self.gen}


class Server:
    def __init__(self, backend, name, out_dir):
        self.backend, self.name, self.out = backend, name, Path(out_dir)
        self.lock = threading.Lock()
        self.run_id = self.thread = self.stop_evt = self.result = None

    def start(self, run_id):
        with self.lock:
            if self.thread and self.thread.is_alive():
                print(f"discarding unfinished capture {self.run_id}", flush=True)
                self.stop_evt.set()
                self.thread.join(timeout=120)

            self.run_id, self.stop_evt, self.result = run_id, threading.Event(), None
            started = threading.Event()

            def work():
                try:
                    self.result = self.backend.capture(self.stop_evt, started)
                except Exception as e:
                    self.result = e
                    started.set()

            self.thread = threading.Thread(target=work, daemon=True)
            self.thread.start()

        started.wait(timeout=30)

        return {"ok": True, "run_id": run_id, "t_host": time.time()}

    def stop(self, run_id):
        if not self.thread or run_id != self.run_id:
            return {"ok": False, "error": f"not capturing {run_id}"}
        
        self.stop_evt.set()
        self.thread.join(timeout=120)
        self.thread = None

        if isinstance(self.result, Exception) or self.result is None:
            return {"ok": False, "error": repr(self.result)}
        
        blocks, extra = self.result

        if len(blocks) < 2:
            return {"ok": False, "error": f"only {len(blocks)} power samples"}
        
        d = self.out / run_id
        d.mkdir(parents=True, exist_ok=True)

        with open(d / "power_trace.csv", "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t0", "t1", "p_w", "energy_counter_j"])
            for t0, t1, p, e in blocks:
                w.writerow([f"{t0:.6f}", f"{t1:.6f}", f"{p:.6f}", e if e == "" else f"{e:.4f}"])

        dur = blocks[-1][1] - blocks[0][0]

        meta = {"ok": True, "run_id": run_id, "backend": self.name, "device": str(self.backend.serial),
                "n_samples": len(blocks), "max_gap_s": max(b[1] - b[0] for b in blocks),
                "t_first": blocks[0][0], "t_last": blocks[-1][1],
                "mean_power_w": sum(p * (t1 - t0) for t0, t1, p, _ in blocks) / dur, **extra}
        
        (d / "capture.json").write_text(json.dumps(meta, indent=2))

        return meta


def make_handler(srv):
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            req = json.loads(self.rfile.readline())
            cmd = req.get("cmd")

            if cmd == "sync":
                reply = {"t_host": time.time()}
            elif cmd == "start":
                reply = srv.start(req["run_id"])
            elif cmd == "stop":
                reply = srv.stop(req["run_id"])
            elif cmd == "trace":
                f = srv.out / req["run_id"] / "power_trace.csv"
                if f.exists():
                    data = f.read_bytes()
                    self.wfile.write((json.dumps({"ok": True, "bytes": len(data)}) + "\n").encode())
                    self.wfile.write(data)
                    return
                reply = {"ok": False, "error": "no trace"}
            elif cmd == "status":
                reply = {"capturing": bool(srv.thread), "run_id": srv.run_id, "backend": srv.name}
            else:
                reply = {"ok": False, "error": f"unknown cmd {cmd}"}
            self.wfile.write((json.dumps(reply) + "\n").encode())

    return Handler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", default=cfg.get("POWER_BACKEND", "shelly"), choices=["shelly"])
    ap.add_argument("--shelly-host", default=cfg.get("SHELLY_HOST", ""))
    ap.add_argument("--poll-hz", type=float, default=float(cfg.get("SHELLY_POLL_HZ", 5)))
    ap.add_argument("--port", type=int, default=cfg.POWER_PORT)
    ap.add_argument("--out", default=str(cfg.REPO_ROOT / cfg.get("POWER_OUT_DIR", "data/power")))
    ap.add_argument("--test", action="store_true", help="print 10 readings and exit")
    a = ap.parse_args()

    backend = ShellyBackend(a.shelly_host, a.poll_hz, None if a.test else a.out)
    if a.test:
        for _ in range(10):
            p, e = backend.read()
            print(f"{time.strftime('%H:%M:%S')}  {p:7.2f} W   counter {e:12.1f} J", flush=True)
            time.sleep(1)
        return

    srv = Server(backend, a.backend, a.out)
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", a.port), make_handler(srv)) as tcp:
        print(f"power server [{a.backend}] {backend.serial}: serving on :{a.port}, traces -> {a.out}", flush=True)
        try:
            tcp.serve_forever()
        except KeyboardInterrupt:
            print("\nstopped")


if __name__ == "__main__":
    main()
