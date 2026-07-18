# End-to-End User Flow: CIS Level 2 Hardened Amazon Linux 2023 AMI on AWS

This document walks through the complete journey — from a fresh BakeX install to a published, CIS Benchmark Level 2 hardened Amazon Linux 2023 AMI in your AWS account.

---

## Prerequisites

Before you start, confirm the following:

| Requirement | Details |
|---|---|
| AWS account | IAM user or role with EC2 full access + SSM permissions |
| AWS credentials configured | `~/.aws/credentials` or instance role |
| Docker + Docker Compose | For the recommended container path |
| Anthropic API key | Only if using AI Builder; optional for manual flow |

---

## Step 0 — Install and Start BakeX

```bash
git clone https://github.com/invicton/bakex.git
cd bakex
```

Edit `docker-compose.yml` and set your secret key:

```yaml
environment:
  BAKEX_SECRET_KEY: "your-strong-passphrase-here"
  ANTHROPIC_API_KEY: "sk-ant-..."          # optional — only for AI Builder
```

Start the stack:

```bash
docker compose up -d
```

Open **http://localhost:8001** in your browser.

The BakeX home page confirms the engine is running and lists available providers and loaded blueprints.

---

## Step 1 — Add Your AWS Credentials

BakeX mounts `~/.aws` read-only by default. If your credentials are already configured on the host, BakeX picks them up automatically.

To verify or add credentials from the UI:

1. Click **Settings → Integrations** in the top navigation
2. Select the **AWS** provider
3. Enter your `Access Key ID`, `Secret Access Key`, and default `Region` (e.g. `us-east-1`)
4. Click **Save** — BakeX encrypts and stores credentials with AES-128 Fernet

You will see a green **Connected** badge next to the AWS provider once credentials are valid.

---

## Step 2 — Choose Your Path: Wizard, Blueprint, or AI Builder

BakeX offers three entry points. All three produce the same result: a build job driven by a `HardeningBlueprint`.

| Path | Best for |
|---|---|
| **5-Step Wizard** | First-time users, point-and-click configuration |
| **Blueprint file** | Teams with existing YAML, GitOps workflows |
| **AI Builder** | Fast iteration, plain-English specification |

This guide covers all three, starting with the wizard.

---

## Path A — 5-Step Wizard

### Wizard Step 1: OS and Provider

1. Click **Build Image** in the top navigation
2. On the wizard's first step:
   - **Operating System:** `Amazon Linux 2023`
   - **Cloud Provider:** `AWS`
   - **Region:** `us-east-1`
   - **Base Image:** BakeX resolves the current AL2023 minimal AMI from SSM Parameter Store automatically. The resolved AMI ID is shown in the preview panel.
3. Click **Next**

### Wizard Step 2: Storage

CIS Level 2 requires separate partitions for several mount points. Configure the volume layout:

| Mount Point | Device | Size | Filesystem |
|---|---|---|---|
| `/` (root) | EBS root | 15 GB | xfs |
| `/var` | `/dev/sdf` | 2 GB | xfs |
| `/var/tmp` | `/dev/sdg` | 2 GB | xfs |
| `/home` | `/dev/sdh` | 4 GB | xfs |
| swap | `/dev/sdi` | 2 GB | swap |
| `/tmp` | tmpfs | 2 GB | tmpfs |
| `/dev/shm` | tmpfs | — | tmpfs |

**Mount options (auto-applied for CIS L2):**

- `/tmp`, `/var/tmp`, `/dev/shm`: `nosuid,nodev,noexec`
- `/home`: `nosuid,nodev`
- `/var`: `nosuid`

Click **Next**

### Wizard Step 3: Network and Users

**Users:**

- **Root account:** `Lock` (checked) — direct root login disabled
- **Admin user:** `bakex-admin`
  - Groups: `wheel`
  - Shell: `/bin/bash`
  - SSH keys: paste your public key, or leave empty to use AWS key pair

**System settings:**

- Hostname: `hardened-node` (or your naming convention)
- Timezone: `UTC`
- Locale: `en_US.UTF-8`
- SELinux: `enforcing` (AL2023 ships with SELinux; CIS Level 2 requires enforcing mode)

Click **Next**

### Wizard Step 4: Compliance Controls

This is where you select the hardening benchmark and profile:

- **Benchmark:** `CIS Amazon Linux 2023 Benchmark`
- **Profile:** `CIS Level 2 Server` — this is the stricter profile, encompassing all L1 controls plus additional restrictions on services, kernel parameters, and audit configuration
- **Severity threshold:** `medium` — the build will fail if any medium, high, or critical finding is present
- **Fail on findings:** `yes`
- **AIDE:** `enabled` — file integrity monitoring database initialised after hardening
- **FIPS:** `disabled` (enable only if your workload requires FIPS 140-2 validated cryptography)

**Rule overrides** — CIS L2 enforces stricter controls than L1. Review the expanded control list. Common overrides for AWS workloads:

| Rule | Action | Justification |
|---|---|---|
| `ensure_gpgcheck_never_disabled` | `enabled` | Package integrity required |
| `sshd_disable_root_login` | `enabled` | Root SSH prohibited by policy |
| `package_telnet_removed` | `enabled` | Telnet prohibited |
| `sshd_set_max_auth_tries` | `enabled` | Brute-force protection |
| `configure_crypto_policy` | `enabled` | FUTURE:DEFAULT enforced on AL2023 |

Click **Next**

### Wizard Step 5: Review and Launch

The final wizard step shows a generated `HardeningBlueprint` YAML preview. Verify:

- Target: `os: amazon-linux-2023`, `provider: aws`
- Profile: `cis_server_l2`
- Volume layout matches your Step 2 configuration
- Users and SELinux mode are set correctly
- Controls list reflects your Step 4 choices

Click **Download Blueprint** to save the YAML to your local machine or your Git repository before launching.

Click **Launch Build** to start the pipeline.

---

## Path B — Blueprint File (GitOps)

If you prefer to drive builds from version-controlled YAML, use the pre-built CIS Level 2 template as a starting point.

Copy the template:

```bash
cp profiles/templates/amazon-linux-2023-cis-l1-aws.yaml \
   profiles/user/amazon-linux-2023-cis-l2-aws.yaml
```

Edit the key fields for Level 2:

```yaml
bakex_version: "0.5.0"
kind: HardeningBlueprint

metadata:
  name: amzn2023-cis-l2-aws
  version: "1.0.0"
  description: >
    CIS Amazon Linux 2023 Benchmark — Level 2 Server profile.
    Full partition layout, AIDE, SELinux enforcing.

target:
  os: amazon-linux-2023
  arch: x86_64
  provider: aws
  base_image: ami-0230bd60aa48260c6   # update to current AL2023 minimal AMI
  instance_type: t3.medium
  root_volume_size_gb: 15
  extra_volumes:
    - device_name: /dev/sdf
      size_gb: 2
    - device_name: /dev/sdg
      size_gb: 2
    - device_name: /dev/sdh
      size_gb: 2
    - device_name: /dev/sdi
      size_gb: 4

system:
  hostname: hardened-node
  timezone: UTC
  locale: en_US.UTF-8
  selinux_mode: enforcing

filesystem:
  - device: /dev/nvme1n1
    mountpoint: /var
    fstype: xfs
    options: [nosuid]
  - device: /dev/nvme2n1
    mountpoint: /var/tmp
    fstype: xfs
    options: [nosuid, nodev, noexec]
  - device: /dev/nvme3n1
    mountpoint: none
    fstype: swap
  - device: /dev/nvme4n1
    mountpoint: /home
    fstype: xfs
    options: [nosuid, nodev]
  - device: tmpfs
    mountpoint: /tmp
    fstype: tmpfs
    options: [rw, nosuid, nodev, noexec, relatime]
    size: 2G
  - device: tmpfs
    mountpoint: /var/tmp
    fstype: tmpfs
    options: [rw, nosuid, nodev, noexec, relatime]
    size: 1G
  - device: tmpfs
    mountpoint: /dev/shm
    fstype: tmpfs
    options: [rw, nosuid, nodev, noexec, relatime]

users:
  root:
    lock: true
  accounts:
    - name: bakex-admin
      comment: "BakeX-managed admin account"
      groups: [wheel]
      shell: /bin/bash
      ssh_authorized_keys: []

compliance:
  benchmark: xccdf_org.ssgproject.content_benchmark_AMAZON_LINUX_2023
  profile: xccdf_org.ssgproject.content_profile_cis_server_l2
  datastream: /usr/share/xml/scap/ssg/content/ssg-al2023-ds.xml
  fail_on_findings: true
  severity_threshold: medium
  aide: true
  fips: false

hardening:
  strategy: ansible-galaxy
  profile_tier: cis-l2

controls:
  xccdf_org.ssgproject.content_rule_package_telnet_removed:
    enabled: true
    justification: "Telnet prohibited by organisational policy."
  xccdf_org.ssgproject.content_rule_sshd_disable_root_login:
    enabled: true
    justification: "Root SSH login prohibited by CIS L2 and organisational policy."
```

In the UI, go to **Blueprints → Upload** and load the file. BakeX validates the schema on upload and shows any errors inline.

Click **Build** next to the blueprint to launch.

---

## Path C — AI Builder

The fastest path for exploration or rapid iteration.

1. Click **AI Builder** in the navigation
2. Type your requirement:

   ```
   Amazon Linux 2023 on AWS, CIS Level 2 server profile, us-east-1, t3.medium.
   Separate partitions for /var, /var/tmp, /home, and /tmp.
   Lock root, create bakex-admin user in wheel group.
   Enable AIDE. SELinux enforcing.
   Fail the build on any medium or higher finding.
   ```

3. Click **Generate and Build**

The agent streams its reasoning to the UI:

```
[BakeX AI] Generating HardeningBlueprint for Amazon Linux 2023 CIS L2...
[BakeX AI] Blueprint validated. Selecting base image: ami-0230bd60aa48260c6 (us-east-1).
[BakeX AI] Launching build pipeline...
```

From this point the pipeline is fully autonomous. The agent monitors every stage and retries if the compliance grade falls below B.

---

## Step 3 — The Build Pipeline

Regardless of the entry path, the build now runs through five stages. Monitor progress at **Builds → [your build]**.

### Stage 1: Provisioning

**What happens:**

- BakeX calls the AWS provider to create a t3.medium EC2 instance from the base AMI
- Attaches the extra EBS volumes defined in the blueprint
- Configures SSM Session Manager access (no inbound SSH port required)
- Returns the instance ID to the engine

**UI state:** `PROVISIONING` — yellow spinner

**Expected duration:** 60–90 seconds

**Live log output:**

```
[PROVISION] Creating EC2 instance in us-east-1...
[PROVISION] Instance i-0abc1234def567890 launched
[PROVISION] Waiting for SSM agent registration...
[PROVISION] Instance ready. Proceeding to hardening.
```

### Stage 2: Hardening

**What happens:**

BakeX generates a two-phase Ansible run:

**Phase 1 — Pre-hardening playbook** (generated by `playbook_gen.py`):
- Partition and format the extra EBS volumes as xfs
- Configure `/etc/fstab` entries with CIS-required mount options
- Create the `bakex-admin` user account
- Set SELinux to enforcing mode
- Stage FIPS configuration if requested

**Phase 2 — Ansible-Lockdown CIS role**:
- BakeX pulls `ansible-lockdown.amazon2023_cis` from Ansible Galaxy
- Generates role variables from the blueprint `controls` section
  - Each disabled rule sets `AMAZON2023CIS_<rule>: false`
  - CIS Level 2 variables are set: `amazon2023cis_level: 2`
- Runs the role against the provisioned instance
- Post-role: initialises the AIDE database

**UI state:** `HARDENING` — yellow spinner

**Expected duration:** 8–15 minutes (varies by instance size and rule count)

**Live log output:**

```
[HARDEN] Generating pre-hardening playbook...
[HARDEN] Running filesystem layout tasks...
[HARDEN]   ✓ /var formatted and mounted (xfs, nosuid)
[HARDEN]   ✓ /var/tmp formatted and mounted (xfs, nosuid,nodev,noexec)
[HARDEN]   ✓ /home formatted and mounted (xfs, nosuid,nodev)
[HARDEN]   ✓ /tmp configured as tmpfs (nosuid,nodev,noexec)
[HARDEN]   ✓ /dev/shm configured as tmpfs (nosuid,nodev,noexec)
[HARDEN] Installing Ansible-Lockdown AMAZON2023-CIS role...
[HARDEN] Running CIS Level 2 hardening role...
[HARDEN]   Section 1: Initial Setup...  ✓
[HARDEN]   Section 2: Services...       ✓
[HARDEN]   Section 3: Network...        ✓
[HARDEN]   Section 4: Logging/Auditing... ✓
[HARDEN]   Section 5: Access/Auth...    ✓
[HARDEN]   Section 6: System Maintenance... ✓
[HARDEN] Initialising AIDE database...  ✓
[HARDEN] Hardening complete.
```

### Stage 3: Scanning

**What happens:**

BakeX runs OpenSCAP against the hardened instance:

```bash
oscap xccdf eval \
  --profile xccdf_org.ssgproject.content_profile_cis_server_l2 \
  --results-arf /tmp/results-arf.xml \
  --report /tmp/report.html \
  /usr/share/xml/scap/ssg/content/ssg-al2023-ds.xml
```

The parser reads the ARF XML output and:
- Counts pass/fail/notchecked per rule
- Computes a weighted compliance score (0–100%)
- Assigns a letter grade: A (≥90%), B (≥80%), C (≥70%), D (≥60%), F (<60%)
- Checks whether any finding exceeds `severity_threshold`
- If `fail_on_findings: true` and the grade is below the threshold, the build transitions to `FAILED`

**UI state:** `SCANNING` — yellow spinner

**Expected duration:** 3–6 minutes

**Live log output:**

```
[SCAN] Running OpenSCAP CIS Level 2 evaluation...
[SCAN] Rules evaluated: 241
[SCAN]   Pass:         228
[SCAN]   Fail:          10
[SCAN]   Not checked:    3
[SCAN] Compliance score: 94.6%
[SCAN] Grade: A
[SCAN] No critical or high findings.
[SCAN] 10 medium findings present — within accepted threshold.
[SCAN] Scan passed. Proceeding to snapshot.
```

If the scan fails, the UI shows the findings table and you can review, adjust controls, and rebuild.

### Stage 4: Snapshot

**What happens:**

- BakeX creates an AMI from the hardened instance
- Tags it with compliance metadata:
  ```
  bakex:profile     = cis_server_l2
  bakex:os          = amazon-linux-2023
  bakex:grade       = A
  bakex:score       = 94.6
  bakex:built-by    = bakex
  bakex:blueprint   = amzn2023-cis-l2-aws
  bakex:build-date  = 2026-04-21
  ```
- Returns the AMI ID to the engine

**UI state:** `SNAPSHOTTING` — yellow spinner

**Expected duration:** 2–4 minutes

**Live log output:**

```
[SNAPSHOT] Creating AMI from instance i-0abc1234def567890...
[SNAPSHOT] AMI ami-0fed9876543210abc registered.
[SNAPSHOT] Tagging with compliance metadata...
[SNAPSHOT] Done.
```

### Stage 5: Teardown

**What happens:**

- Terminates the ephemeral EC2 instance
- Detaches and deletes the build EBS volumes
- Removes any temporary security groups created by the build

**UI state:** `COMPLETE` — green checkmark

**Live log output:**

```
[TEARDOWN] Terminating instance i-0abc1234def567890...
[TEARDOWN] Cleaning up build volumes...
[TEARDOWN] Build complete.
```

---

## Step 4 — Review the Build Summary

After the build completes, the **Build Summary** page shows:

```
┌─────────────────────────────────────────────────────────────────┐
│  BUILD COMPLETE                                                 │
├─────────────────────────────────────────────────────────────────┤
│  Golden Image:      ami-0fed9876543210abc                       │
│  Region:            us-east-1                                   │
│  OS:                Amazon Linux 2023                           │
│  Profile:           CIS Level 2 Server                         │
│                                                                 │
│  Compliance Grade:  A                                           │
│  Score:             94.6%                                       │
│                                                                 │
│  Findings                                                       │
│    Critical:  0                                                 │
│    High:      0                                                 │
│    Medium:    10                                                 │
│    Low:       3                                                  │
│                                                                 │
│  Build duration:    18m 42s                                     │
│  Blueprint:         amzn2023-cis-l2-aws v1.0.0                 │
│                                                                 │
│  [Download HTML Report]  [Download SARIF]  [Download JSON]      │
│  [View Findings]  [Compare to Previous Build]                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## Step 5 — Review Compliance Findings

Click **View Findings** to open the full OpenSCAP results browser.

Each finding shows:

- Rule ID (e.g. `xccdf_org.ssgproject.content_rule_auditd_data_retention_space_left_action`)
- Title (human-readable)
- Severity
- Result (pass / fail / notchecked)
- Remediation description (from the SCAP datastream)

**Filtering:**
- Filter by severity, result status, or section (1.x Initial Setup, 2.x Services, etc.)
- Search by rule ID or keyword

For medium findings you want to accept: click the rule, add a justification, and save the exception. The exception is recorded in the audit log and reflected in subsequent scan comparisons.

---

## Step 6 — Export Reports

### HTML Report

Click **Download HTML Report** for a printable, self-contained compliance report. Suitable for auditors, change advisory boards, and compliance evidence packages.

Sections include:
- Executive summary (score, grade, finding counts)
- Full rule-by-rule results
- Benchmark metadata (CIS Amazon Linux 2023 Benchmark, version, date)
- System metadata (hostname, OS version, scan date)

### SARIF 2.1.0 Export

Click **Download SARIF** to get a SARIF 2.1.0 report. Import into:
- **GitHub Advanced Security** — appears as code scanning results on your repository
- **Azure DevOps** — integrates with Security Centre findings
- **Any SARIF-aware scanner** (SonarQube, Semgrep, Checkmarx)

### JSON Export

Machine-readable findings for downstream pipeline logic:

```json
{
  "grade": "A",
  "score": 94.6,
  "findings": {
    "critical": 0,
    "high": 0,
    "medium": 10,
    "low": 3
  },
  "artifact": {
    "id": "ami-0fed9876543210abc",
    "region": "us-east-1",
    "type": "ami"
  }
}
```

---

## Step 7 — Gate Your CI/CD Pipeline

Now that you have a hardened AMI and a verified compliance grade, plug the pipeline gate into your deployment workflow.

### GitHub Actions example

```yaml
name: Build and gate on compliance

on:
  push:
    paths:
      - 'profiles/user/amazon-linux-2023-cis-l2-aws.yaml'

jobs:
  image-build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Trigger BakeX build
        id: build
        run: |
          RESP=$(curl -sf \
            -H "X-API-Key: ${{ secrets.BAKEX_API_KEY }}" \
            -H "Content-Type: application/json" \
            -d @profiles/user/amazon-linux-2023-cis-l2-aws.yaml \
            "${{ vars.BAKEX_URL }}/api/builder/build")
          echo "job_id=$(echo $RESP | jq -r '.job_id')" >> $GITHUB_OUTPUT

      - name: Wait for build to complete
        run: |
          JOB_ID=${{ steps.build.outputs.job_id }}
          for i in $(seq 1 40); do
            STATUS=$(curl -sf \
              -H "X-API-Key: ${{ secrets.BAKEX_API_KEY }}" \
              "${{ vars.BAKEX_URL }}/api/builder/build/$JOB_ID" \
              | jq -r '.status')
            echo "Build status: $STATUS"
            [[ "$STATUS" == "COMPLETE" || "$STATUS" == "FAILED" ]] && break
            sleep 60
          done

      - name: Gate on compliance grade
        run: |
          RESULT=$(curl -sf \
            -H "X-API-Key: ${{ secrets.BAKEX_API_KEY }}" \
            "${{ vars.BAKEX_URL }}/api/builder/build/${{ steps.build.outputs.job_id }}")
          GRADE=$(echo "$RESULT" | jq -r '.grade')
          AMI=$(echo "$RESULT" | jq -r '.artifact_id')
          echo "AMI: $AMI — Grade: $GRADE"
          [[ "$GRADE" =~ ^[AB]$ ]] || (echo "Compliance gate failed: grade $GRADE" && exit 1)
          echo "AMI_ID=$AMI" >> $GITHUB_ENV

      - name: Publish AMI ID
        run: echo "Published: $AMI_ID"
```

---

## Step 8 — Set Up Drift Monitoring

Once the golden image is published, schedule periodic compliance scans against your running fleet to detect drift.

In the UI: **Compliance Scanner → New Scan**

Or via API (cron example, runs daily at 02:00):

```bash
# trigger-scan.sh
curl -sf \
  -H "X-API-Key: $BAKEX_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "target": "10.0.1.50",
    "benchmark": "xccdf_org.ssgproject.content_benchmark_AMAZON_LINUX_2023",
    "profile": "xccdf_org.ssgproject.content_profile_cis_server_l2"
  }' \
  "$BAKEX_URL/api/pipeline/scan"
```

Add a webhook in **Settings → Webhooks** to receive a notification when drift is detected (any rule regresses from pass to fail). BakeX signs all webhook payloads with HMAC-SHA256.

---

## End State

At this point you have:

| Artifact | Details |
|---|---|
| **Hardened AMI** | `ami-0fed9876543210abc` — tagged with CIS L2, grade A, score 94.6% |
| **Compliance Report** | HTML + SARIF + JSON — ready for auditors and CI/CD systems |
| **Blueprint YAML** | Version-controlled, reusable, diff-friendly |
| **Pipeline gate** | Build fails if compliance grade drops below A or B |
| **Drift monitoring** | Periodic scans + webhook alerts on regression |

Every team member launching instances uses the same AMI. Every instance starts with a verified, documented, CIS Level 2 baseline. Any change to the blueprint goes through the same pipeline — provision, harden, scan, gate, publish.

That is the BakeX workflow.
