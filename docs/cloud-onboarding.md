# Cloud Onboarding Reference

Stratum onboarding is intentionally transparent: every cloud template is readable, reviewable, and replaceable with manual role creation.

## Required Admin Access

The onboarding operator needs permission to create and assign provider-specific roles:

| Provider | Required admin capability |
|---|---|
| AWS | Create IAM roles, policies, instance profiles, and PassRole permissions |
| Azure | Create custom RBAC roles and assign roles at the target scope |
| GCP | Enable APIs, create custom IAM roles, assign IAM roles, create service accounts, and create firewall rules |

Customers that cannot run templates directly can copy the permissions from `deploy/` and create equivalent roles manually.

## AWS

Path: [`deploy/aws`](../deploy/aws)

Use CloudFormation:

- `stratum-scanner-role.yaml`
- `stratum-builder-role.yaml`

Outputs:

- `StratumRoleArn`
- `ExternalId`
- `InstanceProfileName`
- `RegionHint`

## Azure

Path: [`deploy/azure`](../deploy/azure)

Use ARM subscription templates:

- `stratum-scanner-role.json`
- `stratum-builder-role.json`

The template assigns a custom role to an existing Entra service principal. It does not create or output a client secret.

Outputs:

- `SubscriptionId`
- `ResourceGroupName`
- `Location`
- `RoleDefinitionId`
- `RoleAssignmentScope`

## GCP

Path: [`deploy/gcp`](../deploy/gcp)

Use Terraform modules:

- `scanner/`
- `builder/`

The modules create a custom IAM role, optionally create a Stratum service account, assign IAP tunnel access, and create the IAP SSH firewall rule.

Outputs:

- `project_id`
- `zone`
- `network`
- `subnetwork`
- `service_account_email`
- `iam_member`

## Manual Review Workflow

1. Open the provider template/module under `deploy/`.
2. Review the exact permission actions.
3. Apply through your normal cloud change process.
4. Paste the outputs into Stratum.
5. Run **Test Connectivity** before starting builds.
