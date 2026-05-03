# GCP Onboarding

Stratum uses Terraform modules for GCP onboarding. Google Cloud Deployment Manager is deprecated, so Terraform is the safest public launch format and can be run locally or through Google Cloud Infrastructure Manager.

The Terraform must be applied by a GCP principal that can enable services, create custom IAM roles, assign IAM roles, create service accounts, and create firewall rules. Customers can review the full permission set in the module and create equivalent IAM bindings manually if their security process requires it.

## Modules

| Module | Use case | Creates resources |
|---|---|---|
| `scanner/` | Scan existing images or private VM targets | Custom IAM role, optional service account, IAP SSH firewall rule |
| `builder/` | Build hardened GCP Custom Images | Custom IAM role, optional service account, IAP SSH firewall rule |

## Quick Start

```bash
cd deploy/gcp/builder
terraform init
terraform apply \
  -var="project_id=my-gcp-project" \
  -var="zone=us-central1-a" \
  -var="network=default"
```

If you already have a service account or user principal, pass it explicitly:

```bash
terraform apply \
  -var="project_id=my-gcp-project" \
  -var="principal=serviceAccount:stratum@example.iam.gserviceaccount.com"
```

## Stratum Fields

After apply, copy these outputs into **Integrations -> GCP**:

| Terraform output | Stratum field |
|---|---|
| `project_id` | GCP Project ID |
| `zone` | Zone |
| `network` | VPC Network |
| `subnetwork` | Subnetwork |
| `service_account_email` | Service Account Email |

For authentication, prefer Application Default Credentials or service account impersonation. Paste `service_account_json` only when your organization allows user-managed service account keys.

## Security Notes

- The modules do not create service account keys by default.
- The builder role can create and delete temporary instances, disks, and custom images, which can incur costs.
- The IAP firewall rule allows TCP 22 only from `35.235.240.0/20` to instances tagged `stratum-build` or `stratum-scan`.
- Customers can inspect `main.tf` to review every granted permission before applying.
