#!/usr/bin/env bash
# One-time setup of the always-on Swing Desk computer (Google Cloud free e2-micro, Ubuntu 24.04).
# Run it on the VM:  curl -fsSL https://raw.githubusercontent.com/OnlyFaudel/swing-desk/main/deploy/setup_vm.sh | bash
set -euo pipefail
REPO_HTTPS="https://github.com/OnlyFaudel/swing-desk.git"
REPO_SSH="git@github.com:OnlyFaudel/swing-desk.git"

echo "== 1/6 System packages and a 2 GB safety swap (the free VM only has 1 GB of memory)"
sudo apt-get update -y -qq && sudo apt-get install -y -qq python3-venv git
if ! swapon --show | grep -q swapfile; then
  sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
  echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi
sudo timedatectl set-timezone America/New_York

echo "== 2/6 A separate 'desk' user that runs the bot"
id desk >/dev/null 2>&1 || sudo useradd -m -s /bin/bash desk

echo "== 3/6 Download the bot and install it (takes a few minutes)"
[ -d /home/desk/swing-desk ] || sudo -u desk git clone -q "$REPO_HTTPS" /home/desk/swing-desk
[ -d /home/desk/venv ] || sudo -u desk python3 -m venv /home/desk/venv
sudo -u desk /home/desk/venv/bin/pip install -q --upgrade pip
sudo -u desk /home/desk/venv/bin/pip install -q -r /home/desk/swing-desk/requirements.txt
sudo -u desk git -C /home/desk/swing-desk config user.name "Swing Desk VM"
sudo -u desk git -C /home/desk/swing-desk config user.email "OnlyFaudel@users.noreply.github.com"

echo "== 4/6 A key so this computer can save the bot's updates to GitHub"
if [ ! -f /home/desk/.ssh/id_ed25519 ]; then
  sudo -u desk mkdir -p /home/desk/.ssh
  sudo -u desk ssh-keygen -q -t ed25519 -N "" -C "swing-desk-vm" -f /home/desk/.ssh/id_ed25519
  sudo -u desk sh -c 'ssh-keyscan -t ed25519 github.com >> /home/desk/.ssh/known_hosts 2>/dev/null'
fi
sudo -u desk git -C /home/desk/swing-desk remote set-url origin "$REPO_SSH"

echo "== 5/6 The keys file (only root and the bot can read it)"
if [ ! -f /etc/swingdesk.env ]; then
  sudo tee /etc/swingdesk.env >/dev/null <<'ENV'
ANTHROPIC_API_KEY=
NTFY_TOPIC=
NTFY_TOKEN=
ALPACA_KEY=
ALPACA_SECRET=
ALPACA_PAPER=true
REDDIT_CLIENT_ID=
REDDIT_SECRET=
AUTO_GIT=1
ENV
  sudo chmod 600 /etc/swingdesk.env
fi

echo "== 6/6 The always-on service (starts itself after any reboot or crash)"
sudo cp /home/desk/swing-desk/deploy/swingdesk.service /etc/systemd/system/
sudo systemctl daemon-reload

echo
echo "================ DONE WITH SETUP. Two things left: ================"
echo "A) Copy this whole line into GitHub > swing-desk > Settings > Deploy keys > Add deploy key"
echo "   (title: vm, and TICK 'Allow write access'):"
echo
sudo cat /home/desk/.ssh/id_ed25519.pub
echo
echo "B) Put your keys in:   sudo nano /etc/swingdesk.env      (Ctrl+O, Enter, Ctrl+X to save)"
echo "Then start it:         sudo systemctl enable --now swingdesk"
echo "Watch it work:         journalctl -u swingdesk -f      (Ctrl+C stops watching, not the bot)"
