# Getting Started

From zero to a hardened golden image with compliance evidence. This is the
canonical first-run guide; the fastest read is the five numbered steps below,
and the deepest is the [worked example](#worked-example) that follows every
pipeline stage of a real build.

## 1. Start BakeX

Pick one:

```bash
# Docker Compose (recommended — all system tools preinstalled)
git clone https://github.com/invicton/bakex.git && cd bakex
docker compose up
# → http://localhost:8001

# Published image
docker run -p 8000:8000 rrskris/bakex:latest
# → http://localhost:8000

# PyPI (host must provide Ansible + OpenSCAP for real builds)
pip install "bakex[all-providers]"
bakex serve --port 8000              # or: uvicorn bakex.main:app --port 8000
# → http://localhost:8000
```

**First login:** any username + your admin token as the password. If you didn't
set `BAKEX_ADMIN_TOKEN`, a token was generated on first startup and saved to
`data/.admin_token` (also printed in the startup logs).

## 2. Onboard a provider

Go to **Integrations**, select a provider, and use its onboarding card.

| Provider | Admin action | BakeX input |
|---|---|---|
| AWS | Launch CloudFormation stack or manually create the equivalent IAM role | Role ARN, External ID, Instance Profile Name, Region |
| Azure | Deploy ARM template or manually create the equivalent custom RBAC role | Tenant ID, Client ID, Client Secret, Subscription ID, Resource Group, Region |
| GCP | Run native `gcloud` onboarding script or manually create the equivalent IAM bindings | Project ID, Zone, Network, Subnetwork, optional Service Account Email |
| KVM (local) | none — builds run on the BakeX host itself | nothing; no cloud account required |

The onboarding user must have admin-level permission to create and assign the
required cloud permissions. BakeX shows the full permission set so security
teams can review it or reproduce it manually — details in
[Cloud Onboarding](cloud-onboarding.md).

> **No cloud account?** The `kvm` provider builds hardened qcow2/raw images
> locally with QEMU/KVM — download of the official upstream cloud image,
> hardening, scanning, and snapshot all happen on your machine.

## 3. Test connectivity

After saving provider fields, click **Test Connectivity**. A successful test
means BakeX can authenticate and make a low-risk read call to the provider.

## 4. Build a golden image

Open **Builder** and choose your path:

- **5-step wizard** — pick OS/provider, storage, network/users, compliance
  controls, review and launch.
- **Blueprint file** — upload or paste a `HardeningBlueprint` YAML
  (see the [Blueprint Guide](blueprint-guide.md)); the GitOps-friendly path.
- **AI Builder** — describe the target in plain English
  (`"Amazon Linux 2023 on AWS, CIS Level 2, us-east-1, t3.medium"`); the agent
  writes the blueprint, runs the build, and iterates until the grade passes.

BakeX then: provisions a temporary VM → applies the Ansible-Lockdown
CIS/STIG role → runs OpenSCAP → captures the reusable image → deletes every
temporary build resource. Watch each stage live in the build log.

## 5. Scan and export evidence

Open **Auditor** to scan any image or running target — independent of the
builder. Results include a 0–100 % score with an A–F grade, findings by
severity, and per-rule status. Export as HTML (printable), SARIF 2.1.0
(GitHub Advanced Security, Azure DevOps), or JSON. Drift analysis compares any
two scans and flags rules that regressed or improved.

For CI/CD gating — trigger builds and scans by API and fail pipelines on
grade — see the [Pipeline Guide](pipeline.md).

## Worked example

A complete end-to-end walkthrough — CIS Level 2 Amazon Linux 2023 AMI on AWS,
with real screenshots of every wizard step, all three build paths, each
pipeline stage's log output, and the final compliance report — lives in
[ux-flow-cis-l2-amazon-linux-2023.md](ux-flow-cis-l2-amazon-linux-2023.md).
