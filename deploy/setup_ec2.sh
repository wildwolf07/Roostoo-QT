#!/usr/bin/env bash
# One-time setup on the hackathon EC2 instance (Amazon Linux, via Session Manager).
# Usage: sudo bash deploy/setup_ec2.sh https://github.com/<you>/<repo>.git
set -euo pipefail
REPO_URL="${1:?usage: setup_ec2.sh <repo-url>}"
APP=/opt/roostoo-bot

dnf install -y git python3 python3-pip >/dev/null 2>&1 || yum install -y git python3 python3-pip
if [ ! -d "$APP/.git" ]; then
  git clone "$REPO_URL" "$APP"
fi
chown -R ec2-user:ec2-user "$APP"
sudo -u ec2-user python3 -m venv "$APP/.venv"
sudo -u ec2-user "$APP/.venv/bin/pip" install -q --upgrade pip
sudo -u ec2-user "$APP/.venv/bin/pip" install -q -r "$APP/requirements.txt"

if [ ! -f "$APP/.env" ]; then
  cp "$APP/.env.example" "$APP/.env"
  chown ec2-user:ec2-user "$APP/.env"; chmod 600 "$APP/.env"
  echo ">>> Edit $APP/.env (MODE=live + keys), then: sudo systemctl enable --now roostoo-bot"
fi
cp "$APP/deploy/roostoo-bot.service" /etc/systemd/system/roostoo-bot.service
systemctl daemon-reload
echo "setup done. status: sudo systemctl status roostoo-bot | logs: journalctl -u roostoo-bot -f"
