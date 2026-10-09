#!/usr/bin/env bash
# Deploy a committed version: every live code change == a commit in the public history.
# Usage on EC2: sudo bash /opt/roostoo-bot/deploy/deploy.sh [git-ref]
set -euo pipefail
APP=/opt/roostoo-bot
REF="${1:-main}"
RUN_USER=$(cat /etc/roostoo-bot.user 2>/dev/null || echo ec2-user)
cd "$APP"
sudo -u "$RUN_USER" git fetch --all --tags --quiet
sudo -u "$RUN_USER" git checkout --quiet "$REF"
sudo -u "$RUN_USER" git pull --ff-only --quiet || true
sudo -u "$RUN_USER" "$APP/.venv/bin/pip" install -q -r requirements.txt
sudo -u "$RUN_USER" "$APP/.venv/bin/python" -m unittest -q tests.test_core
systemctl restart roostoo-bot
echo "deployed $(git rev-parse --short HEAD) ($(git log -1 --format=%s))"
