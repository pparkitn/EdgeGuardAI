#!/usr/bin/env bash
#
# Deploy the EdgeGuard AI camera service to a remote machine
# (default: Jetson at JETSON_IP, py38env).
#
# Usage:
#   ./scripts/deploy_cameras.sh
#   JETSON_USER=pparkitn JETSON_HOST=JETSON_IP ./scripts/deploy_cameras.sh
#
# Optional env vars (written to cameras.env on the target):
#   EDGEGUARD_CAMERA_PASSWORD, EDGEGUARD_FFMPEG_PATH
#   INSTALL_SERVICE=1   also install + start the systemd service (needs sudo)

set -euo pipefail

JETSON_USER="${JETSON_USER:-pparkitn}"
JETSON_HOST="${JETSON_HOST:-JETSON_IP}"
REMOTE_DIR="${REMOTE_DIR:-/home/pparkitn/edgeguard}"

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> Deploying camera service to ${JETSON_USER}@${JETSON_HOST}:${REMOTE_DIR}"

ssh "${JETSON_USER}@${JETSON_HOST}" \
    "mkdir -p ${REMOTE_DIR}/cameras ${REMOTE_DIR}/data/embeddings ${REMOTE_DIR}/data/unknown_faces ${REMOTE_DIR}/deploy"

rsync -az \
    "${APP_DIR}/cameras/" \
    "${JETSON_USER}@${JETSON_HOST}:${REMOTE_DIR}/cameras/"

rsync -az \
    "${APP_DIR}/face_recognition/" \
    "${JETSON_USER}@${JETSON_HOST}:${REMOTE_DIR}/face_recognition/"

rsync -az \
    "${APP_DIR}/events.py" \
    "${APP_DIR}/edgeguard_config.py" \
    "${APP_DIR}/config.yaml.example" \
    "${APP_DIR}/requirements-vision.txt" \
    "${APP_DIR}/deploy/edgeguard-cameras.service" \
    "${JETSON_USER}@${JETSON_HOST}:${REMOTE_DIR}/"

# real config.yaml is per-device (gitignored in the repo) - never overwrite it
ssh "${JETSON_USER}@${JETSON_HOST}" \
    "[ -f ${REMOTE_DIR}/config.yaml ] || cp ${REMOTE_DIR}/config.yaml.example ${REMOTE_DIR}/config.yaml"

ssh "${JETSON_USER}@${JETSON_HOST}" bash -s <<EOF
set -e
cd "${REMOTE_DIR}"
~/py38env/bin/pip install -q -r requirements-vision.txt 2>/dev/null || true
mkdir -p data/embeddings data/unknown_faces
echo "==> deps checked on target"
EOF

ENV_FILE="$(mktemp)"

for var in \
    EDGEGUARD_CAMERA_PASSWORD \
    EDGEGUARD_FFMPEG_PATH \
; do
    if [ -n "${!var:-}" ]; then
        printf '%s=%s\n' "$var" "${!var}" >> "$ENV_FILE"
    fi
done

if [ -s "$ENV_FILE" ]; then
    scp -q "$ENV_FILE" "${JETSON_USER}@${JETSON_HOST}:${REMOTE_DIR}/cameras.env"
    ssh "${JETSON_USER}@${JETSON_HOST}" "chmod 600 ${REMOTE_DIR}/cameras.env"
    echo "==> cameras.env written on target"
else
    echo "==> no env overrides set; target keeps its existing cameras.env (if any)"
fi

rm -f "$ENV_FILE"

if [ "${INSTALL_SERVICE:-0}" = "1" ]; then

    ssh "${JETSON_USER}@${JETSON_HOST}" \
        "sudo cp ${REMOTE_DIR}/deploy/edgeguard-cameras.service /etc/systemd/system/ && \
         sudo systemctl daemon-reload && \
         sudo systemctl enable --now edgeguard-cameras"

    echo "==> systemd service installed and started"
fi

echo "==> Deploy complete. Start with:"
echo "    ssh ${JETSON_USER}@${JETSON_HOST} 'cd ${REMOTE_DIR} && EDGEGUARD_CAMERA_PASSWORD=... ~/py38env/bin/python -m cameras.main'"
echo "    or install the service: INSTALL_SERVICE=1 ./scripts/deploy_cameras.sh"