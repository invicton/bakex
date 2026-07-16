# GCP Onboarding

Statim uses native `gcloud` onboarding scripts and explicit custom-role YAML files for GCP. There is no third-party IaC dependency.

The script must be run by a GCP principal that can enable services, create custom IAM roles, assign IAM roles, create service accounts, and create firewall rules. Customers can review the full permission set in the YAML files and create equivalent IAM bindings manually if their security process requires it.

## Scripts

| Script | Use case | Creates resources |
|---|---|---|
| `scanner/onboard.sh` | Scan existing images or private VM targets | Custom IAM role, optional service account, IAP SSH firewall rule |
| `builder/onboard.sh` | Build hardened GCP Custom Images | Custom IAM role, optional service account, IAP SSH firewall rule |

## Quick Start

```bash
cd deploy/gcp/builder
PROJECT_ID=my-gcp-project \
ZONE=us-central1-a \
NETWORK=default \
./onboard.sh
```

If you already have a service account, user, or group principal, pass it explicitly:

```bash
PROJECT_ID=my-gcp-project \
PRINCIPAL=serviceAccount:statim@example.iam.gserviceaccount.com \
./onboard.sh
```

## Statim Fields

After the script completes, copy these outputs into **Integrations -> GCP**:

| Script output | Statim field |
|---|---|
| `project_id` | GCP Project ID |
| `zone` | Zone |
| `network` | VPC Network |
| `subnetwork` | Subnetwork |
| `service_account_email` | Service Account Email |

For authentication, prefer Application Default Credentials or service account impersonation. Paste `service_account_json` only when your organization allows user-managed service account keys.

## Security Notes

- The scripts do not create service account keys.
- The builder role can create and delete temporary instances, disks, and custom images, which can incur costs.
- The IAP firewall rule allows TCP 22 only from `35.235.240.0/20` to instances tagged `statim-build` or `statim-scan`.
- Customers can inspect `statim-scanner-role.yaml` and `statim-builder-role.yaml` to review every granted permission before applying.
