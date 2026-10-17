#!/usr/bin/env bash
# Record hardware/software versions for the replication package.
# Run on the Pi after pi_setup.sh 
# Output: data/environment/pi_environment_<stamp>.txt
set -uo pipefail
cd "$(dirname "$0")/.."
source config/experiment.env
mkdir -p data/environment
OUT="data/environment/pi_environment_$(date +%Y%m%d_%H%M%S).txt"
{
  echo "# recorded $(date -u +%FT%TZ)"
  echo "## board";      cat /proc/device-tree/model; echo; vcgencmd version; free -h; lsblk -d -o NAME,SIZE,MODEL
  echo "## os";         cat /etc/os-release; uname -a
  echo "## cpu";        lscpu | head -20
  echo "## governor";   cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
  echo "## tools"
  zip -v | sed -n 2p; tar --version | head -1; gzip --version | head -1
  zstd --version; brotli --version; dpkg -s netcat-openbsd | grep Version
  python3 --version; tmux -V; iw --version
  echo "## experiment-runner"; git -C ~/experiment-runner rev-parse HEAD; ~/gw-venv/bin/pip freeze
  echo "## wifi";       iw dev "$WIFI_IFACE" link; iw dev "$WIFI_IFACE" get power_save
  echo "## services";   systemctl list-units --type=service --state=running --no-pager
  echo "## timers";     systemctl list-timers --all --no-pager
  echo "## payload manifest"; cat "$PAYLOAD_ROOT/manifest.json" 2>/dev/null || echo "(not built yet)"
} > "$OUT" 2>&1
echo "wrote $OUT"
