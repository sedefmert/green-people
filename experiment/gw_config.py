#!/usr/bin/env python3
# Shared configuration: config/experiment.env, overridable by environment variables.
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = REPO_ROOT / "config" / "experiment.env"

def _load(path: Path) -> dict:
    values = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.split(" #", 1)[0].strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            values[key.strip()] = val.strip().strip('"').strip("'")
    return values

_FILE = _load(ENV_FILE)

def get(key, default=None):
    return os.environ.get(key, _FILE.get(key, default))

def _float(key, default):
    return float(get(key, default))

SINK_HOST = get("SINK_HOST", "127.0.0.1")
SINK_PORT = int(get("SINK_PORT", 5000))
WIFI_IFACE = get("WIFI_IFACE", "wlan0")
PAYLOAD_ROOT = Path(os.path.expanduser(get("PAYLOAD_ROOT", str(REPO_ROOT / "payloads"))))
ARCHIVE_DIR = Path(get("ARCHIVE_DIR", "/dev/shm"))
IDLE_S = _float("IDLE_S", 60)
COOLDOWN_S = _float("COOLDOWN_S", 120)
SAMPLE_PERIOD_S = _float("SAMPLE_PERIOD_S", 0.2)
IDLE_TRIM_S = _float("IDLE_TRIM_S", 5)
TRANSFER_TIMEOUT_S = _float("TRANSFER_TIMEOUT_S", 3600)
SIMULATE = get("GW_SIMULATE", "0") == "1"
POWER_HOST = get("POWER_HOST", SINK_HOST)
POWER_PORT = int(get("POWER_PORT", 5100))
POWER_LAG_S = _float("POWER_LAG_S", 0.0)
POWER_TAIL_S = _float("POWER_TAIL_S", 3.0)
