# Stratum User Guide

This guide covers the standard launch workflow for local OSS users.

## 1. Start Stratum

```bash
docker compose up -d --build
```

Open `http://localhost:8001`.

## 2. Onboard A Cloud Account

Go to **Integrations**, select a provider, and use the provider onboarding card.

| Provider | Admin action | Stratum input |
|---|---|---|
| AWS | Launch CloudFormation stack or manually create equivalent IAM role | Role ARN, External ID, Instance Profile Name, Region |
| Azure | Deploy ARM template or manually create equivalent custom RBAC role | Tenant ID, Client ID, Client Secret, Subscription ID, Resource Group, Region |
| GCP | Apply Terraform module or manually create equivalent IAM bindings | Project ID, Zone, Network, Subnetwork, optional Service Account Email |

The user running the onboarding template must have admin-level permission to create and assign the required cloud permissions. Stratum shows the full permission set so security teams can review or reproduce it manually.

## 3. Test Connectivity

After saving provider fields, click **Test Connectivity**. A successful test means Stratum can authenticate and make a low-risk read call to the provider.

## 4. Build A Golden Image

Open **Builder**, choose an OS/provider pair, select storage and user settings, choose the CIS/STIG hardening profile, then start the build.

Stratum will:

1. Launch a temporary VM.
2. Apply pre-hardening configuration.
3. Run the selected Ansible-Lockdown role.
4. Run OpenSCAP.
5. Capture a reusable image.
6. Delete temporary build resources.

## 5. Scan And Export Evidence

Open **Auditor** to scan an image or running target. Reports can be exported as HTML, JSON, or SARIF for GitHub Advanced Security, Azure DevOps, and other SARIF-aware tools.
