#!/bin/bash
# Start the TradeShift web app as a systemd service (called by CloudFormation user data).
#
# What it does: installs a systemd unit that runs gunicorn on port 8000 with settings from
#   /etc/tradeshift.env, starts it, and waits until /health answers, so CloudFormation is
#   only told "success" once the server can really serve traffic.
# Inputs:  /etc/tradeshift.env, /opt/tradeshift
# Outputs: running tradeshift-web service; logs in /var/log/tradeshift/
# How to run: bash infra/scripts/web_start.sh
set -euo pipefail
cat > /etc/systemd/system/tradeshift-web.service <<'UNIT'
[Unit]
Description=TradeShift web app (gunicorn)
After=network-online.target
Wants=network-online.target

[Service]
WorkingDirectory=/opt/tradeshift
EnvironmentFile=/etc/tradeshift.env
# Three processes for a t3.micro (2 vCPUs, 1 GB): one can answer /health while two do
# CPU-heavy pages (Python threads share one CPU per process). Logs go to files the
# CloudWatch agent ships.
ExecStart=/opt/tradeshift/venv/bin/gunicorn --workers 3 --threads 2 --timeout 60 --bind 0.0.0.0:8000 \
  --access-logfile /var/log/tradeshift/access.log --error-logfile /var/log/tradeshift/app.log app.app:app
StandardOutput=append:/var/log/tradeshift/app.log
StandardError=append:/var/log/tradeshift/app.log
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
UNIT
systemctl daemon-reload
systemctl enable --now tradeshift-web
for i in $(seq 1 60); do
  if curl -fs http://127.0.0.1:8000/health >/dev/null; then echo "Web app is up"; exit 0; fi
  sleep 5
done
echo "Web app did not start; see /var/log/tradeshift/app.log" >&2
exit 1
