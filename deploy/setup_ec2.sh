#!/usr/bin/env bash
# One-time setup on the hackathon EC2 instance (via Session Manager).
# Works on Amazon Linux (dnf/yum, user ec2-user) and Ubuntu (apt, user ubuntu).
# Usage: sudo bash deploy/setup_ec2.sh https://github.com/<you>/<repo>.git
set -euo pipefail
REPO_URL="${1:?usage: setup_ec2.sh <repo-url>}"
APP=/opt/roostoo-bot

if command -v dnf >/dev/null; then dnf install -y git python3 python3-pip >/dev/null
elif command -v yum >/dev/null; then yum install -y git python3 python3-pip >/dev/null
elif command -v apt-get >/dev/null; then apt-get update -qq && apt-get install -y -qq git python3 python3-venv python3-pip >/dev/null
fi

if id ec2-user >/dev/null 2>&1; then RUN_USER=ec2-user
elif id ubuntu >/dev/null 2>&1; then RUN_USER=ubuntu
else RUN_USER=root; fi

[ -d "$APP/.git" ] || git clone "$REPO_URL" "$APP"
git config --global --add safe.directory "$APP" || true
chown -R "$RUN_USER":"$RUN_USER" "$APP"
sudo -u "$RUN_USER" python3 -m venv "$APP/.venv"
sudo -u "$RUN_USER" "$APP/.venv/bin/pip" install -q --upgrade pip
sudo -u "$RUN_USER" "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"
sudo -u "$RUN_USER" "$APP/.venv/bin/python" -m unittest -q tests.test_core

sed "s/^User=.*/User=$RUN_USER/" "$APP/deploy/roostoo-bot.service" > /etc/systemd/system/roostoo-bot.service
systemctl daemon-reload
echo "$RUN_USER" > /etc/roostoo-bot.user
echo
echo "SETUP OK (python $(python3 --version 2>&1 | cut -d' ' -f2), run user: $RUN_USER)"
[ -f "$APP/.env" ] || echo ">>> Next: create $APP/.env, then: sudo systemctl enable --now roostoo-bot"
