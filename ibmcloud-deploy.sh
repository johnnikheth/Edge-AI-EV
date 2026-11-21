#!/usr/bin/env bash
# ibmcloud-deploy.sh — Deploy Depot EV to IBM Cloud Code Engine
# Owner: AI & Platform lead  (Bob task 05)
#
# Prerequisites (install once):
#   ibmcloud CLI:  https://cloud.ibm.com/docs/cli?topic=cli-install-ibmcloud-cli
#   Plugins:
#     ibmcloud plugin install container-registry
#     ibmcloud plugin install code-engine
#
# Usage:
#   1. Fill in the four variables in the CONFIGURATION section below.
#   2. chmod +x ibmcloud-deploy.sh
#   3. ./ibmcloud-deploy.sh
#
# After a successful run the script prints the app URL — paste it into
# tools/depot-api.openapi.yaml  servers[0].url  then re-import Orchestrate tools.

set -euo pipefail

# ═══════════════════════════════════════════════════════════════
# CONFIGURATION — fill these in before running
# ═══════════════════════════════════════════════════════════════
REGION="us-south"                       # IBM Cloud region (us-south, eu-de, jp-tok, etc.)
RESOURCE_GROUP="default"                # IBM Cloud resource group
CE_PROJECT="depot-ev-project"           # Code Engine project name (create in IBM Cloud console first)
REGISTRY_NS="depot-ev"                  # IBM Container Registry namespace (create with ibmcloud cr namespace-add)
IMAGE_NAME="depot-ev"
IMAGE_TAG="latest"
APP_NAME="depot-ev"

# Persistent volume: Code Engine mounts this at /data so data.db survives restarts.
# A "job run" volume mount is used; for simplicity this script uses Code Engine's
# built-in ephemeral storage note at the end if you need a true PVC.
MOUNT_PATH="/data"

# ═══════════════════════════════════════════════════════════════
# SECRETS — read from .env (never hard-code here)
# ═══════════════════════════════════════════════════════════════
if [ ! -f .env ]; then
  echo "ERROR: .env file not found. Copy .env.example to .env and fill in values."
  exit 1
fi

# Parse .env into shell variables (skip comments and blank lines)
set -o allexport
# shellcheck disable=SC1091
source <(grep -v '^#' .env | grep '=')
set +o allexport

: "${DEPOT_TOKEN:?DEPOT_TOKEN must be set in .env}"

# ═══════════════════════════════════════════════════════════════
# STEP 1 — Log in
# ═══════════════════════════════════════════════════════════════
echo "→ Logging in to IBM Cloud..."
ibmcloud login --apikey "${IBMCLOUD_API_KEY:-}" -r "$REGION" -g "$RESOURCE_GROUP" 2>/dev/null \
  || ibmcloud login -r "$REGION" -g "$RESOURCE_GROUP"   # interactive if no IBMCLOUD_API_KEY

ibmcloud cr login

# ═══════════════════════════════════════════════════════════════
# STEP 2 — Build and push the image
# ═══════════════════════════════════════════════════════════════
FULL_IMAGE="${REGION}.icr.io/${REGISTRY_NS}/${IMAGE_NAME}:${IMAGE_TAG}"

echo "→ Building image: $FULL_IMAGE"
docker build -t "$FULL_IMAGE" .

echo "→ Pushing image..."
docker push "$FULL_IMAGE"

# ═══════════════════════════════════════════════════════════════
# STEP 3 — Target the Code Engine project
# ═══════════════════════════════════════════════════════════════
echo "→ Targeting Code Engine project: $CE_PROJECT"
ibmcloud ce project select --name "$CE_PROJECT"

# ═══════════════════════════════════════════════════════════════
# STEP 4 — Create / update the secrets
# ═══════════════════════════════════════════════════════════════
echo "→ Creating/updating secrets..."

# Build the --from-literal flags dynamically from .env values
SECRET_FLAGS=""
for VAR in DEPOT_TOKEN WATSONX_API_KEY WATSONX_PROJECT_ID WATSONX_URL WATSONX_MODEL \
           OPENEI_API_KEY SF511_API_KEY NREL_API_KEY SSL_CERT_FILE; do
  VAL="${!VAR:-}"
  if [ -n "$VAL" ]; then
    SECRET_FLAGS="$SECRET_FLAGS --from-literal ${VAR}=${VAL}"
  fi
done

# shellcheck disable=SC2086
ibmcloud ce secret create --name depot-ev-secrets $SECRET_FLAGS 2>/dev/null \
  || ibmcloud ce secret update --name depot-ev-secrets $SECRET_FLAGS

# ═══════════════════════════════════════════════════════════════
# STEP 5 — Deploy (create or update) the Code Engine application
# ═══════════════════════════════════════════════════════════════
echo "→ Deploying application: $APP_NAME"

# DB_PATH points to the ephemeral local path inside the container.
# NOTE: Code Engine ephemeral storage does not survive restarts.
# For production persistence, attach an IBM Cloud Object Storage bucket
# via the rclone sidecar pattern or use a managed PostgreSQL/DB2 instance.
# For the lab demo, ephemeral storage is sufficient (data resets on redeploy).
DB_PATH_VAL="${MOUNT_PATH}/data.db"

DEPLOY_CMD=(
  ibmcloud ce application create
  --name "$APP_NAME"
  --image "$FULL_IMAGE"
  --port 8080
  --min-scale 1 --max-scale 1
  --cpu 0.25 --memory 0.5G
  --env DB_PATH="$DB_PATH_VAL"
  --env-from-secret depot-ev-secrets
  --registry-secret ce-auto-icr-private-"$REGION"
)

# Try create first; if the app already exists, update instead
"${DEPLOY_CMD[@]}" 2>/dev/null \
  || ibmcloud ce application update \
       --name "$APP_NAME" \
       --image "$FULL_IMAGE" \
       --env DB_PATH="$DB_PATH_VAL" \
       --env-from-secret depot-ev-secrets

# ═══════════════════════════════════════════════════════════════
# STEP 6 — Get the HTTPS URL and verify
# ═══════════════════════════════════════════════════════════════
echo "→ Waiting for app to be ready..."
ibmcloud ce application get --name "$APP_NAME" --output json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('App URL:', d['status']['url'])" \
  || ibmcloud ce application get --name "$APP_NAME"

APP_URL=$(ibmcloud ce application get --name "$APP_NAME" --output json \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['status']['url'])" 2>/dev/null || echo "")

if [ -n "$APP_URL" ]; then
  echo ""
  echo "╔══════════════════════════════════════════════════════════════╗"
  echo "  Depot EV deployed at: $APP_URL"
  echo ""
  echo "  Next steps:"
  echo "  1. Test:  curl -H 'Authorization: Bearer \$DEPOT_TOKEN' $APP_URL/api/sessions"
  echo "  2. Update tools/depot-api.openapi.yaml  servers[0].url: $APP_URL"
  echo "  3. Re-import Orchestrate tools:"
  echo "       orchestrate tools import -k openapi -f tools/depot-api.openapi.yaml"
  echo "╚══════════════════════════════════════════════════════════════╝"
fi
