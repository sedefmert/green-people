# GreenWarriors: Energy efficiency of data compression on a Raspberry Pi 4

Replication package for *Energy efficiency of Data Compression Algorithms*.

Four components take part in this experiment. 
1. The **Raspberry Pi 4 Model B** is the device under test: it holds the payloads, runs Experiment Runner, compresses and sends the data to team laptop. 
2. A **Shelly Plus Plug S V2** smart plug (model SNPL-10112EU) sits between the wall socket and the Pi's official USB-C power supply and measures the AC power drawn, this is the source of all energy metrics (M6-M8). 
3. The **team laptop** is wired to the dedicated access point, it polls the Shelly over HTTP, controls the Pi over SSH and relays the TCP stream to gl2. 
4. **gl2** (Green Lab server) runs the TCP sink and a supplementary EnergiBridge measurement.

## Repository layout

```
config/experiment.env        all settings (IPs, paths, protocol timings)
setup/pi_setup.sh            one-time Pi setup (packages, quiet system, sudoers, Experiment Runner)
setup/prepare_payloads.py    builds wiki_S / wiki_L, manifest.json, SHA-256 lists and verifies them
setup/record_environment.sh  record hardware/software versions of the Pi
sink/sink.py                 TCP sink: counts and discards bytes, replies with the count, logs JSONL
sink/run_sink_gl2.sh         starts sink, session-long EnergiBridge on gl2 (tmux)
relay/start_relay.sh         laptop relay, pi:5001 -> laptop:5001, laptop:5000 -> gl2:5000 (auto-reconnect)
relay/local_sink.sh          fallback sink on the laptop (only if the relay is too slow)
power/power_server.py       laptop: polls the Shelly per run, stores the power trace, clock-sync endpoint
experiment/RunnerConfig.py   Experiment Runner config: run table + hooks
experiment/power_client.py   Pi side: clock sync, start/stop capture, fetch trace
experiment/sampler.py        5 Hz sampler: /proc/stat, wlan0 tx_bytes
experiment/metrics.py        M1-M8, energy above idle, validity checks
experiment/pi_probe.py       vcgencmd / iw / counters
experiment/treatments.py     treatment commands
experiment/run.sh            starts a session: pilot | warmup | main | rerun
pilot/                       clock-alignment check, sampler overhead, relay throughput, pilot summary
analysis/analysis.py         data analysis: descriptives, plots, ANOVA / ART, Tukey, BH, bootstrap, Spearman
analysis/gl2_energy.py       supplementary gl2 energy per run
data/                        everything produced by the session
```

## Step 1 - Get the repository and fill in the configuration

On the laptop:

```bash
git clone <repo-url> greenwarriors-replication-package && cd greenwarriors-replication-package
```

Edit `config/experiment.env`: `SINK_HOST` and `POWER_HOST` (both the laptop's IP and Port on the access point), `SHELLY_HOST` (the plug's IP), `PAYLOAD_ROOT` on the Pi, and `JUMP_HOST`, `JUMP_USER`, `GL2_HOST`, `GL2_USER`, `SSH_KEY` of the Green Lab server.

## Step 2 - Shelly plug and power server (once)

1. **Put the plug on the network.** then open its web page (`http://192.168.33.1`). Connect it to the dedicated access point. Give it a fixed IP, switch off Shelly Cloud and Bluetooth in its settings, and update the firmware once. When the `power/power_server.py` starts it saves the plug's model, firmware and settings to `data/power/shelly_device.json` for the replication package.
2. **Wire it:** Directly connect: wall socket -> Shelly -> official Pi power supply -> Pi. Nothing else between.
3. **Test it from the laptop** 

```bash
python3 power/power_server.py --test          # 10 readings: W and the cumulative counter
```

With the Pi idle you should see a few watts, changing slightly from second to second. If the plug is not found, check `SHELLY_HOST` and that laptop and plug are on the same network.

4. **Start the power server** on the laptop, it stays running for the whole session:

```bash
python3 power/power_server.py                 # polls the Shelly, listens on :5100
```

Shelly reports the power about once per second (the server polls at 5 Hz, which only avoids adding delay), and each reading is an average over roughly the preceding second. It measures AC power at the wall, so the numbers include the power supply's own losses.

## Step 3 - Prepare the Raspberry Pi (once)

1. Flash **Raspberry Pi OS Lite 64-bit (bookworm)** with **Raspberry Pi Imager**. In the Imager settings set user, enable SSH with your public key, and pre-configure the Wi-Fi with the dedicated access point. Boot the Pi, powered through the Shelly, with no peripherals (headless mode).
2. From the laptop, copy the repository and run the setup:

```bash
rsync -a --exclude data/ ./ <pi-user>@<pi-ip>:~/greenwarriors-replication-package/
ssh <pi-user>@<pi-ip>
cd ~/greenwarriors-replication-package
bash setup/pi_setup.sh          # packages, disables timers/daemons, sudoers rule, Experiment Runner
exit                            # log out once so all the changes applies
ssh <pi-user>@<pi-ip> 'vcgencmd measure_temp; vcgencmd get_throttled'   # throttled=0x0 expected (If not check the power supply)
```

`pi_setup.sh` disables the apt timers, cron, bluetooth and avahi, adds a NOPASSWD sudoers rule for `/usr/local/sbin/gw-drop-caches` only, and installs Experiment Runner into `~/experiment-runner` with a venv in `~/gw-venv`. CPU governor and Wi-Fi power-save stay at their defaults.

## Step 4 - Dataset and payloads (once)

On the laptop, download the Simple English Wikipedia plain-text dataset from Kaggle (`https://www.kaggle.com/datasets/ffatty/plain-text-wikipedia-simpleenglish`) and copy it to the Pi:

```bash
pip install kaggle
kaggle datasets download -d ffatty/plain-text-wikipedia-simpleenglish -p dataset_raw --unzip
du -sh dataset_raw && find dataset_raw -type f | head      # expect < 400 MB of <= 1 MB text files
rsync -a dataset_raw/ <pi-user>@<pi-ip>:~/dataset_raw/
```

On the Pi, build the two fixed payloads. If the download also contains a single combined file next to the split files, leave it out with `--exclude` so text is not counted twice.

```bash
cd ~/greenwarriors-replication-package
python3 setup/prepare_payloads.py build --source ~/dataset_raw --root ~/greenwarriors-replication-package/data/payloads --small-mb 50
# e.g. add:  --exclude "AllCombined.txt"
python3 setup/prepare_payloads.py verify --root ~/greenwarriors-replication-package/data/payloads
bash setup/record_environment.sh
```

`manifest.json` records per payload the file count, total bytes, an aggregate SHA-256, and `tar_stream_bytes`, the size of `tar -cf - DIR`, which is the expected byte count for the baseline. Experiment Runner re-verifies the checksums at the start of every session. Copy `manifest.json` and the two `.sha256` files into `data/payloads/`.

## Step 5 - Network

Configure the dedicated access point as an isolated network Place the Pi 2m from the AP with line of sight and do not move either during the session.

```bash
sudo nmcli dev wifi connect "<SSID>" password "<pass>" ifname wlan0
iw dev wlan0 link          # expect freq: 5180, a stable signal, tx bitrate ~ 400+ MBit/s
```

Keep the laptop awake for the whole session (macOS: `caffeinate -dims` in new terminal). Before and after every run the Pi measures its clock offset to the laptop (best of 15 round trips over the control port) and maps its phase marks onto the power-trace timestamps, interpolating linearly to absorb clock drift.

## Step 6 - Start the receiver on gl2 (each session)

Connect through the green lab jump host and copy the repository to gl2:

```bash
scp -O <server_hostname>:~/greenwarriors-replication-package/
ssh <server_hostname>
cd ~/greenwarriors-replication-package
energibridge --summary sleep 1               # sanity check from the handout
bash sink/run_sink_gl2.sh 10                 # sink + EnergiBridge for up to 10 h, inside tmux 'gw_sink'
```

Logs go to `~/greenwarriors/gl2_logs/` (`sink_log.json`, `energibridge_<stamp>.csv`, `gl2_env_<stamp>.txt`).

## Step 7 - Start the relay on the laptop (each session)

```bash
bash relay/start_relay.sh        # keep this terminal open, it reconnects automatically upon failure
```

The Pi connects Laptop via `0.0.0.0:LOCAL_SINK_PORT` and the laptop forwards via `127.0.0.1:SINK_PORT`.
It runs `ssh -N -g -L 0.0.0.0:LOCAL_SINK_PORT:127.0.0.1:SINK_PORT` through the jump host.

## Step 8 - Smoke test

From the Pi:

```bash
nc -N <SINK_HOST> <SINK_PORT> < /dev/null          # set SINK_PORT=5001 in config/experiment.env
head -c 10000000 /dev/zero | nc -N <SINK_HOST> <SINK_PORT>   # bytes=10000000
cd ~/greenwarriors-replication-package/experiment && python3 -c "import power_client as p; print(p.sync())"   # rtt_s should be a few ms
```

## Step 9 - Pilot (optional)

Run everything on the Pi inside tmux (`tmux new -s gw`), so a dropped SSH connection does not stop the session.

**9a - Clock alignment and Shelly delay.** The Pi makes eight 5-second all-core CPU bursts at known instants; the script checks where the power edges appear in the Shelly trace compared with the mapped phase marks:

```bash
python3 pilot/clock_check.py 8 5
```

A Shelly typically shows its edges about half a second to a second late. Set the printed `POWER_LAG_S` in `config/experiment.env` on the Pi and run the check again; it should then report a residual below 50 ms.

**9b - Sampler overhead.** Three times 120 s idle without and with the 5 Hz sampler:

```bash
python3 pilot/sampler_overhead.py 120 3
```

**9c - Does the relay limit throughput?** Start `bash relay/local_sink.sh` on the laptop (port 5001), then on the Pi:

```bash
bash pilot/throughput_check.sh 300
```

If the relay is clearly slower than the laptop sink, the Wi-Fi link is not the bottleneck any more. In that case run the experiment against the laptop sink instead (`SINK_PORT=5001` in `config/experiment.env` on the Pi).

**9d - Pilot runs.** Three runs per cell for baseline, tar.zst and tar.br on both payloads (18 runs):

```bash
bash experiment/run.sh pilot
```

Check every run is `valid=True` (`column -s, -t < experiment/experiments/greenwarriors_pilot/run_table.csv | less -S`). Any `invalid_reason` (`byte_mismatch`, `throttling`, `no_sink_reply`, `too_few_samples`, `power_gap*`, `power_capture_error`, `clock_sync_rtt`) must be fixed before the main session.

## Step 10 - Warm-up

```bash
bash experiment/run.sh warmup          # one run per treatment on the large payload
```

Then estimate the session length:

```bash
python3 pilot/summarise_pilot.py experiment/experiments/greenwarriors_pilot/run_table.csv \
                                 experiment/experiments/greenwarriors_warmup/run_table.csv
```

## Step 11 - Main session (100 runs)

Confirm the sink, the relay, the power server and `caffeinate` are running. Then, on the Pi inside tmux(`tmux new -s gw`):

```bash
bash experiment/run.sh main
```

Each run prints a line such as `tar.zst/L rep 3: E=412.7 J -> OK`. The run table is `experiment/experiments/greenwarriors_main/run_table.csv`; every run has its own directory with `power_trace.csv`, `samples.csv` and `phases.json`, and the laptop keeps its own copy of each trace in `data/power/`. Detach with `Ctrl-b d`; do not use the Pi or the AP while it runs.

**If the session is interrupted** (power cut, SSH drop that killed tmux, power server restarted), make sure the `power/power_server.py` is running (an unfinished capture is discarded automatically), then run the same command: Experiment Runner resumes at the first row that is not `DONE`, keeping the original shuffled order. Do not edit `RunnerConfig.py` between parts, so the run table stays identical.

## Step 12 - Re-execute invalid runs

```bash
bash experiment/run.sh rerun experiment/experiments/greenwarriors_main/run_table.csv
```

This builds a new table with one run per invalid row (column `rerun_of`), in a new random order (seed 2027), and runs it with the same protocol. The original rows stay in the main table with their `invalid_reason`. If a re-execution is invalid again, rename the finished directory and re-execute its invalid rows:

```bash
mv experiment/experiments/greenwarriors_rerun experiment/experiments/greenwarriors_rerun1
bash experiment/run.sh rerun experiment/experiments/greenwarriors_rerun1/run_table.csv
```

Pass every rerun table (`--rerun ...rerun1/run_table.csv ...rerun/run_table.csv`) when performing the analysis later.

## Step 13 - Collect the data

On the laptop:

```bash
mkdir -p data/raw data/gl2 data/pilot data/environment data/payloads
rsync -a <pi-user>@<pi-ip>:~/greenwarriors-replication-package/experiment/experiments/ data/raw/
rsync -a <pi-user>@<pi-ip>:~/greenwarriors-replication-package/data/ data/
rsync -a <pi-user>@<pi-ip>:~/greenwarriors/payloads/{manifest.json,wiki_S.sha256,wiki_L.sha256} data/payloads/
scp -O <server_hostname>:~/greenwarriors/gl2_logs/ data/gl2/
# data/power/ is already on the laptop (written by the power server)
```

Stop the gl2 side with `tmux kill-session -t gw_sink`.

## Step 14 - Data Analysis

```bash
pip install -r analysis/requirements.txt
python3 analysis/analysis.py --main data/raw/greenwarriors_main/run_table.csv \
                             --rerun data/raw/greenwarriors_rerun/run_table.csv --out data/results
python3 analysis/gl2_energy.py --eb data/gl2/energibridge_<stamp>.csv --sink-log data/gl2/sink_log.jsonl \
        --runs data/raw/greenwarriors_main/run_table.csv data/raw/greenwarriors_rerun/run_table.csv \
        --out data/results/gl2_energy.csv
```

`analysis.py` writes `summary.md`, `hypothesis_tests.csv` (H1.1-H3.3 with method used, F, p, BH-adjusted p, partial eta squared), `posthoc_pairwise.csv`, `h34_energy_saving.csv` (Delta in J and %, bootstrap 95% CI, `energy_efficient`), `h35_spearman.csv`, `descriptives.csv` and the figures (boxplots, density plots, Q-Q plots, stacked M7 bar chart). It warns if any cell does not have exactly 10 valid runs. A metric is tested with a two-way ANOVA when the residuals pass Shapiro-Wilk and Levene; otherwise a log, square-root or reciprocal transform is tried; if none passes, an Aligned Rank Transform ANOVA with pairwise Wilcoxon rank-sum tests and Cliff's delta is used.
