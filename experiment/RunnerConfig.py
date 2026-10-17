# This script defines the configuration for the experiment runner. 
# It specifies the run table, the hooks for each phase of the experiment, and the output directory for results. 
# It also handles payload verification, power server interaction, and data collection during each run.
import csv
import json
import os
import random
import re
import resource
import signal
import subprocess
import sys
import time
from os.path import dirname, realpath
from pathlib import Path
from typing import Any, Dict, Optional

from EventManager.Models.RunnerEvents import RunnerEvents
from EventManager.EventSubscriptionController import EventSubscriptionController
from ConfigValidator.Config.Models.RunTableModel import RunTableModel
from ConfigValidator.Config.Models.FactorModel import FactorModel
from ConfigValidator.Config.Models.RunnerContext import RunnerContext
from ConfigValidator.Config.Models.OperationType import OperationType
from ProgressManager.Output.OutputProcedure import OutputProcedure as output

sys.path.insert(0, dirname(realpath(__file__)))
import gw_config as cfg                       # noqa: E402
import metrics                                # noqa: E402
import power_client as pc                     # noqa: E402
import pi_probe as probe                      # noqa: E402
from treatments import (TREATMENTS, COMPRESS, SEND_ARCHIVE, SEND_BASELINE,  # noqa: E402
                        PAYLOAD_DIRS, archive_name, bash)

SEED = 2026
MODE = os.environ.get("GW_MODE", "main")
SINK_REPLY = re.compile(r"GW_SINK conn=(\d+) bytes=(\d+)")

DATA_COLUMNS = [
    "repetition",
    # M1 / M2
    "cpu_util_mean_compress", "cpu_util_peak_compress",
    "cpu_util_mean_transmit", "cpu_util_peak_transmit",
    "cpu_time_compress_s", "cpu_time_transmit_s", "cpu_time_total_s",
    # M3 / M4 / M5
    "wlan_tx_mb", "archive_bytes", "compression_ratio", "t_compress_s", "t_transmit_s",
    # M6 / M7 / M8
    "energy_compress_j", "energy_transmit_j", "energy_total_j", "energy_per_mb_j",
    "energy_total_counter_j",
    "energy_tx_above_idle_j", "energy_compress_above_idle_j", "p_idle_w",
    # clock alignment / capture quality
    "clock_offset_pre_s", "clock_drift_s", "sync_rtt_max_s", "power_max_gap_s",
    # covariates and validity
    "temp_before_c", "temp_after_c", "throttled_before", "throttled_after",
    "rssi_before_dbm", "rssi_after_dbm", "tx_bitrate_mbps",
    "payload_bytes", "expected_bytes", "sink_bytes", "sink_conn_id", "bytes_ok",
    "n_samples", "valid", "invalid_reason", "t_wall_start",
]

# RUsage of the child processes (compress + transmit) in seconds. 
# This is used to compute the CPU time spent in the measured phases.
def _rusage_children_s():
    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
    return ru.ru_utime + ru.ru_stime

# Parse the repetition number from a run_id.
def _parse_rep(run_id: str):
    m = re.search(r"repetition_(\d+)", run_id)
    return int(m.group(1)) if m else ""

# RunnerConfig is the configuration for the Experiment Runner. 
# It defines the run table, the hooks, and the output directory.
class RunnerConfig:
    ROOT_DIR = Path(dirname(realpath(__file__)))

    name:                       str             = f"greenwarriors_{MODE}"
    results_output_path:        Path            = ROOT_DIR / "experiments"
    operation_type:             OperationType   = OperationType.AUTO
    time_between_runs_in_ms:    int             = int(cfg.COOLDOWN_S * 1000)

    def __init__(self):
        EventSubscriptionController.subscribe_to_multiple_events([
            (RunnerEvents.BEFORE_EXPERIMENT, self.before_experiment),
            (RunnerEvents.BEFORE_RUN,        self.before_run),
            (RunnerEvents.START_RUN,         self.start_run),
            (RunnerEvents.START_MEASUREMENT, self.start_measurement),
            (RunnerEvents.INTERACT,          self.interact),
            (RunnerEvents.STOP_MEASUREMENT,  self.stop_measurement),
            (RunnerEvents.STOP_RUN,          self.stop_run),
            (RunnerEvents.POPULATE_RUN_DATA, self.populate_run_data),
            (RunnerEvents.AFTER_EXPERIMENT,  self.after_experiment),
        ])

        self.run_table_model = None
        self.manifest = json.loads((cfg.PAYLOAD_ROOT / "manifest.json").read_text())
        self.rerun_source = {}
        output.console_log(f"GreenWarriors config loaded (mode={MODE}, simulate={cfg.SIMULATE})")

    # Create the run table model based on the mode (pilot, warmup, main, rerun).
    # In rerun mode, the source CSV file is read from the environment variable GW_R
    def create_run_table_model(self) -> RunTableModel:
        random.seed(SEED)

        if MODE == "rerun":
            src = os.environ["GW_RERUN_SOURCE"]

            with open(src) as f:
                rows = [r for r in csv.DictReader(f) if r.get("valid") != "True"]

            if not rows:
                raise SystemExit(f"No invalid runs in {src}; nothing to re-execute.")
            
            self.rerun_source = {r["__run_id"]: r for r in rows}
            random.seed(SEED + 1) 
            factors = [FactorModel("rerun_of", sorted(self.rerun_source))]
            reps, cols = 1, ["treatment", "payload"] + DATA_COLUMNS
        else:
            treatments, payloads, reps = {
                "pilot":  (["none", "tar.zst", "tar.br"], ["S", "L"], 3),
                "warmup": (TREATMENTS, ["L"], 1),
                "main":   (TREATMENTS, ["S", "L"], 10),
            }[MODE]

            factors = [FactorModel("treatment", treatments), FactorModel("payload", payloads)]
            cols = DATA_COLUMNS
        self.run_table_model = RunTableModel(factors=factors, repetitions=reps, data_columns=cols, shuffle=True)

        return self.run_table_model

    def _cell(self, context):
        run = context.execute_run

        if MODE == "rerun":
            src = self.rerun_source[run["rerun_of"]]
            rep = src.get("repetition") or _parse_rep(run["rerun_of"])

            return src["treatment"], src["payload"], rep
        
        return run["treatment"], run["payload"], _parse_rep(run["__run_id"])

    # Before the experiment starts, verify payload checksums, check power server and sink reachability, and create the session.json file.
    def before_experiment(self) -> None:
        exp = Path(self.experiment_path)
        exp.mkdir(parents=True, exist_ok=True)

        if os.environ.get("GW_SKIP_VERIFY") != "1":
            output.console_log("Verifying payload checksums against manifest.json ...")
            r = subprocess.run([sys.executable, str(cfg.REPO_ROOT / "setup" / "prepare_payloads.py"),
                                "verify", "--root", str(cfg.PAYLOAD_ROOT)])
            
            if r.returncode != 0:
                raise SystemExit("Payload verification failed - aborting.")
        
        try:
            st = pc._request({"cmd": "status"}, timeout=10)
        except OSError as e:
            raise SystemExit(f"power server {cfg.POWER_HOST}:{cfg.POWER_PORT} unreachable: {e}")
        output.console_log(f"power backend: {st.get('backend')}")

        if st.get("capturing"):
            output.console_log(f"power server was still capturing {st.get('run_id')} (interrupted run); "
                               "it is discarded at the next start.")
        
        r = subprocess.run(["bash", "-c", f"nc -N {cfg.SINK_HOST} {cfg.SINK_PORT} < /dev/null"],
                           capture_output=True, text=True, timeout=30)
        
        if not SINK_REPLY.search(r.stdout):
            raise SystemExit(f"Sink {cfg.SINK_HOST}:{cfg.SINK_PORT} did not reply "
                             f"(stdout={r.stdout!r}, stderr={r.stderr!r}). Start sink + relay first.")
        
        (exp / "session.json").write_text(json.dumps({
            "mode": MODE, "seed": SEED, "simulate": cfg.SIMULATE,
            "sink": f"{cfg.SINK_HOST}:{cfg.SINK_PORT}", "started_wall": time.time(),
            "probe": probe.snapshot(), "manifest": self.manifest}, indent=2))

    # Before each run, remove old archives in /dev/shm and drop the page cache (requires sudoers rule).
    def before_run(self) -> None:
        for f in cfg.ARCHIVE_DIR.glob("a.*"):
            f.unlink()

        if not probe.drop_caches():
            output.console_log_FAIL("drop_caches failed - is the sudoers rule installed?")

    # Start a run by taking a snapshot of the Pi's state and recording the wall-clock start time.
    def start_run(self, context: RunnerContext) -> None:
        self.before = probe.snapshot()
        self.t_wall_start = time.time()

    def _run_key(self, context):
        return f"{MODE}__{context.execute_run['__run_id']}"

    # Start the power capture and the 5 Hz sampler, and sync the Pi clock with the host clock. Wait for the sampler to be ready.
    def start_measurement(self, context: RunnerContext) -> None:
        self.sync_pre = pc.sync()
        pc.start(self._run_key(context))
        out = Path(context.run_dir) / "samples.csv"

        self.sampler = subprocess.Popen(
            [sys.executable, str(self.ROOT_DIR / "sampler.py"), "--out", str(out),
             "--period", str(cfg.SAMPLE_PERIOD_S)])
        
        ready = out.with_suffix(".ready")
        deadline = time.monotonic() + 10

        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.05)

    # Interact with the Pi by performing the idle baseline, compression, and transmission phases. Record the timestamps, resource usage, and probe snapshots.
    def interact(self, context: RunnerContext) -> None:
        treatment, payload, _ = self._cell(context)
        d = PAYLOAD_DIRS[payload]
        meta = self.manifest["payloads"][payload]
        ph = {"treatment": treatment, "payload": payload, "simulated": cfg.SIMULATE,
              "idle_trim_s": cfg.IDLE_TRIM_S, "payload_bytes": meta["total_bytes"],
              "expected_baseline_bytes": meta["tar_stream_bytes"], "wall": {}}

        def mark(key):
            ph[key] = time.monotonic()
            ph["wall"][key] = time.time()

        # 1. idle baseline
        mark("idle_start")
        time.sleep(cfg.IDLE_S)
        mark("idle_end")

        # 2. compression phase
        archive = cfg.ARCHIVE_DIR / archive_name(treatment)

        if treatment != "none":
            cmd = COMPRESS[treatment].format(archive=archive, dir=d)
            ru0 = _rusage_children_s()
            mark("compress_start")
            r = subprocess.run(bash(cmd), cwd=cfg.PAYLOAD_ROOT, capture_output=True,
                               text=True, timeout=cfg.TRANSFER_TIMEOUT_S)
            mark("compress_end")
            ph["rusage_compress_s"] = _rusage_children_s() - ru0
            ph["compress_rc"], ph["compress_stderr"] = r.returncode, r.stderr[-2000:]
            ph["archive_bytes"] = archive.stat().st_size if archive.exists() else None
            send = SEND_ARCHIVE.format(host=cfg.SINK_HOST, port=cfg.SINK_PORT, archive=archive)
        else:
            ph["compress_start"] = ph["compress_end"] = None
            send = SEND_BASELINE.format(host=cfg.SINK_HOST, port=cfg.SINK_PORT, dir=d)

        # 3. transmission phase
        ph["tx_bytes_before"] = probe.read_tx_bytes()
        ru0 = _rusage_children_s()
        mark("transmit_start")
        r = subprocess.run(bash(send), cwd=cfg.PAYLOAD_ROOT, capture_output=True,
                           text=True, timeout=cfg.TRANSFER_TIMEOUT_S)
        mark("transmit_end")

        ph["rusage_transmit_s"] = _rusage_children_s() - ru0
        ph["tx_bytes_after"] = probe.read_tx_bytes()
        ph["transmit_rc"], ph["transmit_stderr"] = r.returncode, r.stderr[-2000:]

        m = SINK_REPLY.search(r.stdout)

        ph["sink_conn_id"], ph["sink_bytes"] = (int(m.group(1)), int(m.group(2))) if m else (None, None)
        ph["commands"] = {"compress": COMPRESS.get(treatment), "send": send}

        self.after = probe.snapshot()

        ph["throttling_problem"] = probe.throttling_problem(self.before["throttled"],
                                                            self.after["throttled"])
        ph["probe_before"], ph["probe_after"] = self.before, self.after

        self.phases = ph

    # Stop the power capture and the sampler, and sync the Pi clock with the host clock.
    def stop_measurement(self, context: RunnerContext) -> None:
        self.sampler.send_signal(signal.SIGTERM)
        self.sampler.wait(timeout=60)

        time.sleep(cfg.POWER_TAIL_S)

        self.power = pc.stop(self._run_key(context))
        self.sync_post = pc.sync()

    # Stop a run by removing old archives in /dev/shm.
    def stop_run(self, context: RunnerContext) -> None:
        for f in cfg.ARCHIVE_DIR.glob("a.*"):
            f.unlink()

    # Populate the run data by fetching the power trace, computing the metrics, and returning a dict with the results. 
    def populate_run_data(self, context: RunnerContext) -> Optional[Dict[str, Any]]:
        treatment, payload, rep = self._cell(context)
        run_dir = Path(context.run_dir)
        ph = self.phases

        ph.update({"clock_base": pc.BASE, "sync_pre": self.sync_pre, "sync_post": self.sync_post,
                   "power": self.power, "power_lag_s": cfg.POWER_LAG_S,
                   "power_run_key": self._run_key(context)})
        
        (run_dir / "phases.json").write_text(json.dumps(ph, indent=2))
        trace = run_dir / "power_trace.csv"

        if self.power.get("ok"):
            pc.fetch_trace(self._run_key(context), trace)

        blocks = metrics.load_trace(trace, cfg.POWER_LAG_S) if trace.exists() else []
        m = metrics.compute(metrics.load_samples(run_dir / "samples.csv"), blocks, ph,
                            cfg.SAMPLE_PERIOD_S)
        
        row = {**m,
               "repetition": rep,
               "temp_before_c": self.before["temp_c"], "temp_after_c": self.after["temp_c"],
               "throttled_before": hex(self.before["throttled"] or 0),
               "throttled_after": hex(self.after["throttled"] or 0),
               "rssi_before_dbm": self.before["rssi_dbm"], "rssi_after_dbm": self.after["rssi_dbm"],
               "tx_bitrate_mbps": self.before["tx_bitrate_mbps"],
               "t_wall_start": round(self.t_wall_start, 3)}
        
        if MODE == "rerun":
            row.update({"treatment": treatment, "payload": payload})

        cols = self.run_table_model.get_data_columns()
        row = {k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items() if k in cols}
        status = "OK" if row["valid"] else f"INVALID ({row['invalid_reason']})"
        output.console_log(f"{treatment}/{payload} rep {rep}: E={row['energy_total_j']:.1f} J -> {status}")

        return row

    # After the experiment finishes, log a message to copy the experiments/ directory into data/raw/ as per the README instructions.
    def after_experiment(self) -> None:
        output.console_log("Session finished. Copy experiments/ into data/raw/ (README step 13).")

    experiment_path: Path = None
