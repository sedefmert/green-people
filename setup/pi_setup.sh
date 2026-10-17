#!/usr/bin/env bash
# Setup for Raspberry Pi
# Usage:
#     bash setup/pi_setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$(pwd)"
ER_COMMIT=56620fa6e48ef99180824a24369dc2f6ec3d6910 

echo "# 1. Installing Packages"
sudo apt-get update
sudo apt-get install -y zip tar gzip zstd brotli netcat-openbsd tmux iw \
     python3-venv python3-pip git rsync bc

sudo update-alternatives --set nc /bin/nc.openbsd 2>/dev/null || true

echo "# 2. Disabling System Updates and Services"
for unit in apt-daily.timer apt-daily-upgrade.timer man-db.timer fstrim.timer \
            e2scrub_all.timer dpkg-db-backup.timer logrotate.timer \
            unattended-upgrades.service cron.service bluetooth.service hciuart.service \
            triggerhappy.service ModemManager.service cups.service avahi-daemon.service \
            avahi-daemon.socket rpi-eeprom-update.service; do
  sudo systemctl disable --now "$unit" 2>/dev/null && echo "  disabled $unit" || true
done

echo "# 3. Configuring the User"
sudo usermod -aG video "$USER"
sudo tee /usr/local/sbin/gw-drop-caches >/dev/null <<'SH'
#!/bin/sh
sync
echo 3 > /proc/sys/vm/drop_caches
SH
sudo chmod 755 /usr/local/sbin/gw-drop-caches
echo "$USER ALL=(root) NOPASSWORD: /usr/local/sbin/gw-drop-caches" | sudo tee /etc/sudoers.d/gw-drop-caches >/dev/null
sudo chmod 440 /etc/sudoers.d/gw-drop-caches
sudo visudo -cf /etc/sudoers.d/gw-drop-caches

echo "# 4. Installing Experiment Runner"
if [[ ! -d "$HOME/experiment-runner" ]]; then
  git clone https://github.com/S2-group/experiment-runner.git "$HOME/experiment-runner"
fi
git -C "$HOME/experiment-runner" fetch --all -q
git -C "$HOME/experiment-runner" checkout -q "$ER_COMMIT"
python3 -m venv "$HOME/gw-venv"
"$HOME/gw-venv/bin/pip" install -q -r "$HOME/experiment-runner/requirements.txt"

echo "# 5. Sanity Checks"
vcgencmd measure_temp || echo "!! vcgencmd failed (log out/in for the video group)"
vcgencmd get_throttled
iw dev wlan0 link | grep -E "SSID|freq|signal" || echo "!! wlan0 not associated - connect to the dedicated AP (README step 5)"
mkdir -p "$REPO/data"
echo "Done. Log out and back in once to apply the changes."
