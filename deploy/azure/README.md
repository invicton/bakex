# Azure Onboarding

BakeX can use an existing Microsoft Entra service principal instead of broad subscription credentials. Deploy one of these ARM templates at subscription scope, then paste the outputs and service principal secret into **Integrations -> Azure**.

The deployment must be run by an Azure principal that can create custom roles and assign roles at the target scope. Customers can review the full permission set in the template and create equivalent RBAC roles manually if their security process requires it.

## Templates

| Template | Use case | Creates resources |
|---|---|---|
| `bakex-scanner-role.json` | Scan or run command on scoped Azure VMs | Resource group, custom scanner role, role assignment |
| `bakex-builder-role.json` | Build hardened Azure Managed Images | Resource group, custom builder role, role assignment |

Use the builder template for AMI-style managed image builds. Use the scanner template for narrower read/run-command access.

## Required Parameters

- `principalObjectId`: Object ID of the service principal, user, group, or managed identity BakeX will use.
- `principalType`: Usually `ServicePrincipal`.
- `resourceGroupName`: Resource group where BakeX resources are scoped.
- `location`: Default Azure region.
- `roleNamePrefix`: Optional prefix for the custom role name.

The template does not create or return a client secret. Create the app registration/service principal in Microsoft Entra ID, generate a client secret there, and store it in BakeX.

## BakeX Fields

After deployment, copy these values into **Integrations -> Azure**:

| Azure value | BakeX field |
|---|---|
| Tenant ID from Entra ID | Tenant ID |
| Application/client ID from Entra ID | App (Client) ID |
| Client secret from Entra ID | Client Secret |
| `SubscriptionId` output | Subscription ID |
| `ResourceGroupName` output | Resource Group |
| `Location` output | Azure Region |

Then click **Test Connectivity**.

## Security Notes

- The custom role is assigned only at the BakeX resource-group scope.
- Azure Run Command requires `Microsoft.Compute/virtualMachines/runCommand/action`.
- Builder permissions can create VMs, disks, NICs, and managed images, which can incur costs.
