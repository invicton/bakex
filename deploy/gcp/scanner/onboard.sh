#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

: "${PROJECT_ID:?Set PROJECT_ID to the target GCP project ID.}"
REGION="${REGION:-us-central1}"
ZONE="${ZONE:-us-central1-a}"
NETWORK="${NETWORK:-default}"
SUBNETWORK="${SUBNETWORK:-}"
ROLE_ID="${ROLE_ID:-stratumScanner}"
SERVICE_ACCOUNT_ID="${SERVICE_ACCOUNT_ID:-stratum-scanner}"
FIREWALL_RULE="${FIREWALL_RULE:-stratum-allow-iap-ssh}"
PRINCIPAL="${PRINCIPAL:-}"

if ! command -v gcloud >/dev/null 2>&1; then
  echo "gcloud is required. Install the Google Cloud CLI and authenticate as a project admin." >&2
  exit 1
fi

gcloud config set project "${PROJECT_ID}" >/dev/null
gcloud services enable compute.googleapis.com iap.googleapis.com --project "${PROJECT_ID}"

if [[ -z "${PRINCIPAL}" ]]; then
  if ! gcloud iam service-accounts describe "${SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com" --project "${PROJECT_ID}" >/dev/null 2>&1; then
    gcloud iam service-accounts create "${SERVICE_ACCOUNT_ID}" \
      --project "${PROJECT_ID}" \
      --display-name "Stratum scanner service account"
  fi
  PRINCIPAL="serviceAccount:${SERVICE_ACCOUNT_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
fi

if gcloud iam roles describe "${ROLE_ID}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud iam roles update "${ROLE_ID}" --project "${PROJECT_ID}" --file "${SCRIPT_DIR}/stratum-scanner-role.yaml"
else
  gcloud iam roles create "${ROLE_ID}" --project "${PROJECT_ID}" --file "${SCRIPT_DIR}/stratum-scanner-role.yaml"
fi

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member "${PRINCIPAL}" \
  --role "projects/${PROJECT_ID}/roles/${ROLE_ID}" \
  --condition=None

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member "${PRINCIPAL}" \
  --role "roles/iap.tunnelResourceAccessor" \
  --condition=None

if gcloud compute firewall-rules describe "${FIREWALL_RULE}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  gcloud compute firewall-rules update "${FIREWALL_RULE}" \
    --project "${PROJECT_ID}" \
    --network "${NETWORK}" \
    --allow tcp:22 \
    --source-ranges 35.235.240.0/20 \
    --target-tags stratum-build,stratum-scan
else
  gcloud compute firewall-rules create "${FIREWALL_RULE}" \
    --project "${PROJECT_ID}" \
    --network "${NETWORK}" \
    --allow tcp:22 \
    --source-ranges 35.235.240.0/20 \
    --target-tags stratum-build,stratum-scan \
    --description "Allow Stratum SSH through Google Cloud IAP only."
fi

cat <<EOF
Stratum GCP scanner onboarding complete.

Paste these values into Integrations -> GCP:
  project_id: ${PROJECT_ID}
  zone: ${ZONE}
  network: ${NETWORK}
  subnetwork: ${SUBNETWORK}
  service_account_email: ${PRINCIPAL#serviceAccount:}
  iam_member: ${PRINCIPAL}
EOF
