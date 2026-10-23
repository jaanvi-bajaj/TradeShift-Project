#!/bin/bash
# Install TradeShift on an EC2 server from the cloned repo (called by CloudFormation user data).
#
# What it does: downloads the pinned Python wheels from the GitHub release, checks their
#   SHA-256, creates a virtual environment and installs requirements.txt offline from those
#   wheels (no package registry is contacted on the server). Then configures the CloudWatch
#   agent to ship this server's logs.
# Inputs:  $1 wheelhouse URL, $2 expected wheelhouse SHA-256 (may be empty), $3 role: web | batch
# Outputs: /opt/tradeshift/venv, /var/log/tradeshift/, CloudWatch agent running
# How to run: bash infra/scripts/install_app.sh <wheelhouse-url> <sha256> <web|batch>
set -euo pipefail
WHEEL_URL="$1"; WHEEL_SHA="$2"; ROLE="$3"
APP=/opt/tradeshift
WHEELS=/opt/wheelhouse

mkdir -p "$WHEELS" /var/log/tradeshift
curl -fsSL --retry 5 -o /tmp/wheelhouse.tar.gz "$WHEEL_URL"
if [ -n "$WHEEL_SHA" ]; then
  echo "$WHEEL_SHA  /tmp/wheelhouse.tar.gz" | sha256sum -c -   # stop if the file was altered
fi
tar -xzf /tmp/wheelhouse.tar.gz -C "$WHEELS"

python3.11 -m venv "$APP/venv"
"$APP/venv/bin/pip" install --no-index --find-links "$WHEELS" -r "$APP/requirements.txt"

# Ship app and bootstrap logs to CloudWatch Logs (log group created by the stack).
STACK_LOG_GROUP=$(sed -n 's/^LOG_GROUP=//p' /etc/tradeshift.env)
STACK_LOG_GROUP=${STACK_LOG_GROUP:-/tradeshift/$ROLE}
sed -e "s#__LOG_GROUP__#$STACK_LOG_GROUP#g" "$APP/infra/scripts/cloudwatch-agent.json" \
  > /opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json
/opt/aws/amazon-cloudwatch-agent/bin/amazon-cloudwatch-agent-ctl -a fetch-config -m ec2 -s \
  -c file:/opt/aws/amazon-cloudwatch-agent/etc/amazon-cloudwatch-agent.json
echo "TradeShift installed for role $ROLE"
