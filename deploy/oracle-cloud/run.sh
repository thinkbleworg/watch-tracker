#!/usr/bin/env bash
#
# Wrapper script run by cron/systemd on the Oracle VM.
# Loads secrets from .env, activates the venv, runs the
# tracker, and logs with automatic rotation.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$PROJECT_DIR"

# Load secrets (BOT_TOKEN, CHAT_ID) from .env
if [ -f .env ]; then
    set -a
    source .env
    set +a
else
    echo "ERROR: .env not found in $PROJECT_DIR" >&2
    exit 1
fi

source venv/bin/activate

python main.py >> logs/tracker.log 2>&1

# Keep the log from growing forever -- cheap rotation
# without needing logrotate configured separately.
LOG_LINES=$(wc -l < logs/tracker.log)
if [ "$LOG_LINES" -gt 20000 ]; then
    tail -n 10000 logs/tracker.log > logs/tracker.log.tmp
    mv logs/tracker.log.tmp logs/tracker.log
fi
