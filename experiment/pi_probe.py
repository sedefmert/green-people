# Raspberry Pi 4 readings used by the sampler and the run hooks.
import random
import re
import subprocess
from pathlib import Path

import gw_config as cfg

# Run a command and return its stdout
def _run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout

# Read the CPU jiffies from /proc/stat. Returns a tuple of (active, total) jiffies.
def read_cpu_jiffies():
    with open("/proc/stat") as f:
        fields = [int(x) for x in f.readline().split()[1:]]
    idle = fields[3] + (fields[4] if len(fields) > 4 else 0)   # idle + iowait
    total = sum(fields[:8])                                     # exclude guest columns
    return total - idle, total

# Read the number of bytes transmitted over the Wi-Fi interface.
def read_tx_bytes(iface=None):
    return int(Path(f"/sys/class/net/{iface or cfg.WIFI_IFACE}/statistics/tx_bytes").read_text())

# Read the temperature from vcgencmd.
def read_temp_c():
    if cfg.SIMULATE:
        return round(45 + random.random() * 5, 1)
    
    m = re.search(r"temp=([0-9.]+)", _run(["vcgencmd", "measure_temp"]))
    return float(m.group(1)) if m else None

# Read the throttling flags from vcgencmd. The flags are a bitmask of the following:
# 0x1: under-voltage detected
# 0x2: arm frequency capped
# 0x4: currently throttled  
def read_throttled():
    if cfg.SIMULATE:
        return 0
    
    m = re.search(r"throttled=(0x[0-9a-fA-F]+)", _run(["vcgencmd", "get_throttled"]))
    return int(m.group(1), 16) if m else None

# Read the Wi-Fi link quality from `iw dev <iface> link`. Returns a dict with keys:
#   rssi_dbm: signal strength in dBm (negative)
#   tx_bitrate_mbps: transmit bitrate in Mbit/s
#   freq_mhz: frequency in MHz
def read_link():
    if cfg.SIMULATE:
        return {"rssi_dbm": -40 - random.randint(0, 5), "tx_bitrate_mbps": 433.3, "freq_mhz": 5180}
    out = _run(["iw", "dev", cfg.WIFI_IFACE, "link"])
    get = lambda pat: (float(m.group(1)) if (m := re.search(pat, out)) else None)

    return {
        "rssi_dbm": get(r"signal:\s*(-?[0-9.]+)\s*dBm"),
        "tx_bitrate_mbps": get(r"tx bitrate:\s*([0-9.]+)\s*MBit/s"),
        "freq_mhz": get(r"freq:\s*([0-9.]+)"),
    }

# Snapshot of the Pi's state, including temperature, throttling flags, and Wi-Fi link quality.
def snapshot():
    return {"temp_c": read_temp_c(), "throttled": read_throttled(), **read_link()}

# Check if there is a throttling problem based on the before and after states.
def throttling_problem(before, after):
    if before is None or after is None:
        return True
    
    active = (before | after) & 0xF
    new_sticky = (after & ~before) & 0xF0000

    return bool(active or new_sticky)

# Drop the page cache on the Pi. This requires the sudoers rule installed by setup/pi_setup.sh.
def drop_caches():
    subprocess.run(["sync"], check=False)

    if cfg.SIMULATE:
        return True
    r = subprocess.run(["sudo", "-n", "/usr/local/sbin/gw-drop-caches"], capture_output=True)

    return r.returncode == 0
