#!/usr/bin/env bash
# Pull the newest exported GGUF off the cluster, verify it, put it on the Modal volume, redeploy,
# and confirm the live endpoint is serving it.
#
#   ./update_model.sh                 # nano, the model Pay runs
#   ./update_model.sh mini-tools      # any other exported model
#
# The checksum comparison is not ceremony. A half-finished scp leaves a file of the right SIZE with
# the wrong contents, and the only symptom is a model that behaves like the previous one: this
# script exists because that happened, twice, and cost two rounds of recording a demo that was
# quietly running last week's weights.
set -euo pipefail
MODEL="${1:-nano-tools}"
REMOTE="/leonardo_scratch/large/userexternal/imisi000/morena/edge/${MODEL}-Q4_K_M.gguf"
LOCAL="${HOME}/dev/morena/local/${MODEL}-Q4_K_M.gguf"
VOLUME="morena-pay-models"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
URL="${2:-https://vambo--morena-pay-pay-web.modal.run}"

echo "==> remote checksum"
WANT=$(ssh -o BatchMode=yes leonardo "sha256sum $REMOTE" | cut -d' ' -f1)
[ -n "$WANT" ] || { echo "no such file on the cluster: $REMOTE"; exit 1; }
echo "    $WANT"

if [ -f "$LOCAL" ] && [ "$(sha256sum "$LOCAL" | cut -d' ' -f1)" = "$WANT" ]; then
  echo "==> local copy already matches, skipping the download"
else
  echo "==> downloading (this link runs about 150 KB/s, so a 326MB file is ~35 minutes)"
  scp -o BatchMode=yes "leonardo:$REMOTE" "$LOCAL.part"
  mv "$LOCAL.part" "$LOCAL"          # atomic: never leave a half file where the real one goes
fi

GOT=$(sha256sum "$LOCAL" | cut -d' ' -f1)
if [ "$GOT" != "$WANT" ]; then
  echo "CHECKSUM MISMATCH"
  echo "  cluster $WANT"
  echo "  local   $GOT"
  echo "Refusing to upload. Delete $LOCAL and run this again."
  exit 1
fi
echo "==> checksum verified"

echo "==> uploading to the $VOLUME volume"
modal volume put --force "$VOLUME" "$LOCAL" "/${MODEL}-Q4_K_M.gguf"

echo "==> redeploying"
# Stop first: a warm container keeps serving the previous build's files, so a deploy reports
# success while the URL does not change.
modal app stop "$(basename "$APP_DIR")" -y 2>/dev/null || true
sleep 6
( cd "$APP_DIR" && modal deploy serve.py >/dev/null )

echo "==> confirming the live endpoint"
LIVE=$(curl -s -m 400 "$URL/props" | grep -o '"model_path":"[^"]*"' | cut -d'"' -f4)
echo "    serving: ${LIVE:-nothing}"
[ "$LIVE" = "${MODEL}-Q4_K_M.gguf" ] && echo "==> done" || { echo "live endpoint is not serving $MODEL"; exit 1; }
