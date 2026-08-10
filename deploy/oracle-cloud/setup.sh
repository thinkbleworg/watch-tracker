#!/usr/bin/env bash
#
# Run this ON the Oracle Cloud VM, from inside the project
# directory (~/watch-tracker), after the code is already
# there (git clone or scp'd zip).
#
# Usage:
#   cd ~/watch-tracker
#   chmod +x deploy/oracle-cloud/setup.sh
#   ./deploy/oracle-cloud/setup.sh

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

echo "==> Installing system packages"
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git

echo "==> Creating virtualenv"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "==> Creating logs/snapshots dirs"
mkdir -p logs snapshots

if [ ! -f .env ]; then
    echo "==> Creating .env from template -- EDIT THIS FILE NOW"
    cp deploy/oracle-cloud/.env.example .env
    chmod 600 .env
    echo
    echo "    -> nano $PROJECT_DIR/.env"
    echo "    Fill in your real BOT_TOKEN and CHAT_ID, then re-run this script."
    exit 0
fi
chmod 600 .env

echo "==> Testing config loads correctly"
set -a; source .env; set +a
python3 -c "import config; print('BOT_TOKEN set:', bool(config.BOT_TOKEN)); print('CHAT_ID set:', bool(config.CHAT_ID))"

echo "==> Installing systemd units"
sed "s#/home/ubuntu/watch-tracker#$PROJECT_DIR#g" \
    deploy/oracle-cloud/watch-tracker.service | sudo tee /etc/systemd/system/watch-tracker.service > /dev/null

sudo cp deploy/oracle-cloud/watch-tracker.timer /etc/systemd/system/watch-tracker.timer

sudo systemctl daemon-reload
sudo systemctl enable --now watch-tracker.timer

echo
echo "==> Done. Timer status:"
systemctl status watch-tracker.timer --no-pager
echo
echo "Run a first manual test with:"
echo "    sudo systemctl start watch-tracker.service"
echo "    journalctl -u watch-tracker.service -f"
