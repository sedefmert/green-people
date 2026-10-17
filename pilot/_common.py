import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "experiment"))
import gw_config as cfg
import metrics
import power_client as mc

OUT = REPO / "data" / "pilot"

# Capture power and energy consumption of the Pi during a block of code.
class Capture:
    def __init__(self, name):
        self.key = f"pilot__{name}_{time.strftime('%Y%m%d_%H%M%S')}"
        self.marks = {}

    def mark(self, label):
        self.marks[label] = time.monotonic()

    def __enter__(self):
        OUT.mkdir(parents=True, exist_ok=True)
        self.sync_pre = mc.sync()
        mc.start(self.key)
        return self

    def __exit__(self, *exc):
        time.sleep(cfg.POWER_TAIL_S)

        self.power = mc.stop(self.key)
        self.sync_post = mc.sync()
        self.trace_path = OUT / f"{self.key}_power_trace.csv"

        mc.fetch_trace(self.key, self.trace_path)

        self.blocks = metrics.load_trace(self.trace_path, cfg.POWER_LAG_S)
        self.to_host = metrics.host_mapper({"clock_base": mc.BASE, "sync_pre": self.sync_pre,
                                            "sync_post": self.sync_post})
        
        (OUT / f"{self.key}.json").write_text(json.dumps({
            "marks_monotonic": self.marks, "clock_base": mc.BASE, "sync_pre": self.sync_pre,
            "sync_post": self.sync_post, "power": self.power,
            "power_lag_s_applied": cfg.POWER_LAG_S}, indent=2))
        
        return False

    def mean_power(self, a_label, b_label):
        a, b = self.to_host(self.marks[a_label]), self.to_host(self.marks[b_label])
        e, cov = metrics.block_energy(self.blocks, a, b)

        return e / (b - a), cov / (b - a)
