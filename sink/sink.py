#!/usr/bin/env python3
import argparse
import json
import signal
import socket
import sys
import time
from pathlib import Path

CHUNK = 1 << 20

# TCP sink (receiver): accept connections, read until EOF, count bytes, reply with count, log connection info
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1",
                    help="127.0.0.1 behind the SSH relay; 0.0.0.0 for the local fallback sink")
    ap.add_argument("--port", type=int, default=5000)
    ap.add_argument("--log", required=True)
    args = ap.parse_args()

    log = Path(args.log).expanduser()
    log.parent.mkdir(parents=True, exist_ok=True)
    conn_id = 0
    if log.exists():   # continue numbering after a restart
        conn_id = sum(1 for _ in log.open())

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((args.host, args.port))
    srv.listen(1)
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    print(f"sink listening on {args.host}:{args.port}, log={log}", flush=True)

    buf = bytearray(CHUNK)

    while True:
        conn, peer = srv.accept()
        conn_id += 1
        t_accept = time.time()
        t_first = None
        n = 0

        try:
            while True:
                k = conn.recv_into(buf)
                if k == 0:
                    break
                if t_first is None:
                    t_first = time.time()
                n += k
            t_eof = time.time()
            conn.sendall(f"GW_SINK conn={conn_id} bytes={n}\n".encode())
            conn.shutdown(socket.SHUT_WR)
            status = "ok"

        except OSError as e:
            t_eof, status = time.time(), f"error: {e}"

        finally:
            conn.close()
        rec = {"conn_id": conn_id, "peer": f"{peer[0]}:{peer[1]}", "t_accept": t_accept,
               "t_first_byte": t_first, "t_eof": t_eof, "bytes": n, "status": status}
        
        with log.open("a") as f:
            f.write(json.dumps(rec) + "\n")

        mbps = n * 8 / 1e6 / max(t_eof - (t_first or t_accept), 1e-9)
        print(f"conn {conn_id}: {n} bytes, {mbps:.1f} Mbit/s, {status}", flush=True)


if __name__ == "__main__":
    main()
