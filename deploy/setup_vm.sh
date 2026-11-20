#!/usr/bin/env bash
# One-time setup on a fresh Ubuntu VM (Google Cloud e2-micro free tier in us-east1, or any $4-6 VPS).
# Usage: bash setup_vm.sh https://github.com/<you>/swing-desk.git
set -euo pipefail
REPO="$1"
sudo apt-get update -y && sudo apt-get install -y python3-venv git
sudo useradd -m -s /bin/bash desk || true
sudo -u desk git clone "$REPO" /home/desk/swing-desk
sudo -u desk python3 -m venv /home/desk/venv
sudo -u desk /home/desk/venv/bin/pip install -r /home/desk/swing-desk/requirements.txt
# keys live ONLY here, readable by root/systemd, never in the repo
sudo tee /etc/swingdesk.env >/dev/null <<'ENV'
ANTHROPIC_API_KEY=paste-here
NTFY_TOPIC=paste-here
ALPACA_KEY=paste-here
ALPACA_SECRET=paste-here
ALPACA_PAPER=true
AUTO_GIT=1
ENV
sudo chmod 600 /etc/swingdesk.env
sudo cp /home/desk/swing-desk/deploy/swingdesk.service /etc/systemd/system/
sudo timedatectl set-timezone America/New_York
echo "Now: sudo nano /etc/swingdesk.env (paste keys), set \"runner\": \"vm\" in config.json and push it,"
echo "and in GitHub: Settings > Secrets and variables > Actions > Variables > add RUNNER = vm (stops the 15-minute GitHub runs),"
echo "give the VM push access (a GitHub deploy key with write access) so the dashboard updates, then:"
echo "  sudo systemctl daemon-reload && sudo systemctl enable --now swingdesk && journalctl -u swingdesk -f"
