#!/usr/bin/env bash
#
# Deploy the EdgeGuard AI voice broadcaster to a remote machine
# (default: Raspberry Pi at PI_IP).
#
# Usage:
#   ./scripts/deploy_voice.sh
#   PI_HOST=PI_IP PI_USER=pi ./scripts/deploy_voice.sh
#
# Optional env vars (written to voice.env on the target):
#   AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY,
#   EDGEGUARD_MQTT_HOST, EDGEGUARD_SPEAKERS, ...
#   INSTALL_SERVICE=1   also install + start the systemd service

set -euo pipefail

PI_USER="${PI_USER:-pi}"
PI_HOST="${PI_HOST:-PI_IP}"
REMOTE_DIR="${REMOTE_DIR:-/home/pi/edgeguard}"

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Deploying voice broadcaster to ${PI_USER}@${PI_HOST}:${REMOTE_DIR}"

ssh "${PI_USER}@${PI_HOST}" \
    "mkdir -p ${REMOTE_DIR}/voice ${REMOTE_DIR}/data/audio ${REMOTE_DIR}/logs"

rsync -az \
    "${APP_DIR}/voice/" \
    "${PI_USER}@${PI_HOST}:${REMOTE_DIR}/voice/"

rsync -az \
    "${APP_DIR}/edgeguard_config.py" \
    "${APP_DIR}/config.yaml.example" \
    "${APP_DIR}/requirements-voice.txt" \
    "${PI_USER}@${PI_HOST}:${REMOTE_DIR}/"

# real config.yaml is per-device (gitignored in the repo) - never overwrite it
ssh "${PI_USER}@${PI_HOST}" \
    "[ -f ${REMOTE_DIR}/config.yaml ] || cp ${REMOTE_DIR}/config.yaml.example ${REMOTE_DIR}/config.yaml"

ssh "${PI_USER}@${PI_HOST}" bash -s <<EOF
set -e
mkdir -p "${REMOTE_DIR}/data/audio" "${REMOTE_DIR}/logs"
cd "${REMOTE_DIR}"

if [ ! -d .venv ]; then
    python3 -m venv .venv
fi

.venv/bin/pip install --upgrade pip -q
.venv/bin/pip install -r requirements-voice.txt -q

echo "==> venv ready on target"
EOF

ENV_FILE="$(mktemp)"

for var in \
    AWS_ACCESS_KEY_ID \
    AWS_SECRET_ACCESS_KEY \
    AWS_DEFAULT_REGION \
    EDGEGUARD_MQTT_HOST \
    EDGEGUARD_MQTT_PORT \
    EDGEGUARD_MQTT_TOPIC \
    EDGEGUARD_POLLY_REGION \
    EDGEGUARD_POLLY_VOICE \
    EDGEGUARD_HTTP_PORT \
    EDGEGUARD_SPEAKERS \
    EDGEGUARD_LOCAL_PLAYBACK \
    EDGEGUARD_ANNOUNCE_RECOGNIZED \
    EDGEGUARD_ANNOUNCEMENT_COOLDOWN \
; do
    if [ -n "${!var:-}" ]; then
        printf '%s=%s\n' "$var" "${!var}" >> "$ENV_FILE"
    fi
done

if [ -s "$ENV_FILE" ]; then
    scp -q "$ENV_FILE" "${PI_USER}@${PI_HOST}:${REMOTE_DIR}/voice.env"
    echo "==> voice.env written on target"
else
    echo "==> no env overrides set; target keeps its existing voice.env (if any)"
fi

rm -f "$ENV_FILE"

if [ "${INSTALL_SERVICE:-0}" = "1" ]; then

    scp -q \
        "${APP_DIR}/deploy/edgeguard-voice.service" \
        "${PI_USER}@${PI_HOST}:${REMOTE_DIR}/deploy/"

    ssh "${PI_USER}@${PI_HOST}" \
        "sudo cp ${REMOTE_DIR}/deploy/edgeguard-voice.service /etc/systemd/system/ && \
         sudo systemctl daemon-reload && \
         sudo systemctl enable --now edgeguard-voice"

    echo "==> systemd service installed and started"
fi

echo "==> Deploy complete. Start with:"
echo "    ssh ${PI_USER}@${PI_HOST} 'cd ${REMOTE_DIR} && .venv/bin/python -m voice.broadcaster'"
echo "    or install the systemd unit: INSTALL_SERVICE=1 ./scripts/deploy_voice.sh"