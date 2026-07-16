# Cloud Onboarding Reference

BakeX onboarding is intentionally transparent: every cloud template is readable, reviewable, and replaceable with manual role creation.

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

- `bakex-scanner-role.yaml`
- `bakex-builder-role.yaml`

When using the public GitHub templates, download the YAML and upload it in CloudFormation. The AWS console quick-create `templateURL` field does not accept GitHub raw URLs as a supported template source.

Set `TrustedPrincipalArn` to the IAM user or role ARN behind the credentials BakeX will use. For example, if BakeX uses access keys for `arn:aws:iam::123456789012:user/bakex-ci`, that exact ARN must be the trusted principal. The same principal also needs an identity policy allowing `sts:AssumeRole` on the generated BakeX role.

Outputs:

- `BakeXRoleArn`
- `ExternalId`
- `InstanceProfileName`
- `RegionHint`

In **Integrations -> AWS**, enter the base AWS credentials and stack name, click **Import Outputs**, then click **Test Connectivity**. If BakeX reports that base credentials cannot assume the configured Role ARN, fix `TrustedPrincipalArn` or the caller's `sts:AssumeRole` permission.

## Azure

Path: [`deploy/azure`](../deploy/azure)

Use ARM subscription templates:

- `bakex-scanner-role.json`
- `bakex-builder-role.json`

The template assigns a custom role to an existing Entra service principal. It does not create or output a client secret.

Outputs:

- `SubscriptionId`
- `ResourceGroupName`
- `Location`
- `RoleDefinitionId`
- `RoleAssignmentScope`

## GCP

Path: [`deploy/gcp`](../deploy/gcp)

Use native `gcloud` scripts and custom-role YAML files:

- `scanner/onboard.sh`
- `builder/onboard.sh`

The scripts create or update a custom IAM role, optionally create a BakeX service account, assign IAP tunnel access, and create the IAP SSH firewall rule.

Outputs:

- `project_id`
- `zone`
- `network`
- `subnetwork`
- `service_account_email`
- `iam_member`

## Manual Review Workflow

1. Open the provider template, script, or role file under `deploy/`.
2. Review the exact permission actions.
3. Apply through your normal cloud change process.
4. Paste the outputs into BakeX.
5. Run **Test Connectivity** before starting builds.
