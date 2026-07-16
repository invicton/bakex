# AWS Onboarding

BakeX can use an AWS IAM role instead of long-lived access keys. Download one of these CloudFormation templates, create a stack in the AWS account where BakeX should scan or build images, then paste the stack outputs into **Integrations -> AWS**.

The stack must be launched by an AWS principal that can create IAM roles, policies, instance profiles, and PassRole permissions. Customers can review the full permission set in the template and create equivalent resources manually if their security process requires it.

## Templates

| Template | Use case | Creates resources |
|---|---|---|
| `bakex-scanner-role.yaml` | Scan existing AMIs or EC2 instances | BakeX scanner role, EC2 SSM instance role, instance profile |
| `bakex-builder-role.yaml` | Build hardened golden AMIs | BakeX builder role, EC2 SSM instance role, instance profile |

Use the scanner template first for demos. Use the builder template only when you are ready for BakeX to launch EC2 instances and create AMIs/snapshots.

## Launch From The AWS Console

CloudFormation quick-create `templateURL` expects a supported template URL source such as S3. GitHub raw URLs are not accepted by the AWS console for that field.

For the public GitHub templates:

1. Open the template link from BakeX.
2. Save the YAML file locally.
3. In CloudFormation, choose **Create stack -> With new resources**.
4. Select **Upload a template file**.
5. Upload the saved YAML file and continue through stack creation.

## Required Parameters

- `TrustedPrincipalArn`: IAM principal allowed to assume the BakeX role. The default trusts the current AWS account root so test stacks can be created without looking up an ARN. For production, replace it with the specific IAM user or role configured for BakeX.
- `ExternalId`: A unique string you paste into BakeX along with the role ARN. The template default, `bakex-onboarding`, is provided so demos do not fail validation; replace it with a customer-unique value for production.
- `RoleNamePrefix`: Optional name prefix for created IAM roles.

The trusted principal must match the base credentials BakeX uses to connect to AWS. If you enter access keys for `arn:aws:iam::123456789012:user/bakex-ci`, set `TrustedPrincipalArn` to that exact user ARN. If you use an AWS profile, set it to the IAM user or role behind that profile.

That same principal must also have an identity policy allowing it to call `sts:AssumeRole` on the generated BakeX role:

```json
{
  "Effect": "Allow",
  "Action": "sts:AssumeRole",
  "Resource": "arn:aws:iam::123456789012:role/BakeXBuilderRole"
}
```

If BakeX reports `base credentials cannot assume the configured Role ARN`, either update the CloudFormation stack with the correct `TrustedPrincipalArn` or attach the `sts:AssumeRole` permission shown above to the IAM user/role used by BakeX.

## BakeX Fields

After the stack completes, enter your base AWS credentials and stack name in **Integrations -> AWS**, then click **Import Outputs**. BakeX reads the CloudFormation outputs and fills:

- `BakeXRoleArn` -> `Role ARN`
- `ExternalId` -> `External ID`
- `InstanceProfileName` -> `IAM Instance Profile Name`
- `RegionHint` -> `Region`

Then click **Test Connectivity**.

## Security Notes

- The trust policy requires `sts:ExternalId`.
- The scanner template has fewer permissions than the builder template.
- Both templates create an EC2 instance profile with `AmazonSSMManagedInstanceCore` so temporary scan/build instances can receive SSM commands.
- Builder permissions can create EC2 instances, AMIs, EBS snapshots, and related costs. Use a test account or budget alerts for first runs.
