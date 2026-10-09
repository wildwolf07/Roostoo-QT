#!/usr/bin/env bash
# Deploy a committed version: every live code change == a commit in the public history.
# Usage on EC2: sudo bash /opt/roostoo-bot/deploy/deploy.sh [git-ref]
set -euo pipefail
APP=/opt/roostoo-bot
REF="${1:-main}"
cd "$APP"
sudo -u ec2-user git fetch --all --tags --quiet
sudo -u ec2-user git checkout --quiet "$REF"
sudo -u ec2-user git pull --ff-only --quiet || true
sudo -u ec2-user "$APP/.venv/bin/pip" install -q -r requirements.txt
sudo -u ec2-user "$APP/.venv/bin/python" -m unittest -q tests.test_core
systemctl restart roostoo-bot
echo "deployed $(git rev-parse --short HEAD) ($(git log -1 --format=%s))"
