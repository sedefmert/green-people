# data/

Filled in after the session (README step 13). Committed to the replication package.

| Path | Content | Produced by |
|---|---|---|
| `raw/greenwarriors_main/` | `run_table.csv` (100 rows) + one directory per run with `power_trace.csv` (Shelly power readings as time blocks, laptop clock), `samples.csv` (5 Hz CPU counters and wlan0 tx_bytes) and `phases.json` (phase marks, clock sync, getrusage, commands, covariates) | Experiment Runner on the Pi + power server |
| `raw/greenwarriors_rerun/` | re-executions of invalid runs (column `rerun_of` points to the original row) | Experiment Runner on the Pi |
| `raw/greenwarriors_pilot/`, `raw/greenwarriors_warmup/` | pilot and warm-up runs (excluded from the analysis) | Experiment Runner on the Pi |
| `power/` | the laptop's own copy of every capture (`power_trace.csv`, `capture.json`) | `power/power_server.py` |
| `payloads/` | `manifest.json`, `wiki_S.sha256`, `wiki_L.sha256` | `setup/prepare_payloads.py` |
| `environment/` | Pi hardware/software versions | `setup/record_environment.sh` |
| `gl2/` | `sink_log.jsonl`, EnergiBridge session CSV + summary, gl2 environment | `sink/run_sink_gl2.sh` |
| `pilot/` | clock-alignment check, sampler overhead, relay throughput | `pilot/*` |
| `results/` | tables, figures and `summary.md` | `analysis/*.py` |
