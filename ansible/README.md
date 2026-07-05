# Ansible Hardening Roles

Stratum uses [Ansible-Lockdown](https://github.com/ansible-lockdown) roles to apply CIS/STIG hardening before snapshotting. The roles are installed on demand during the build — you do not need to vendor them manually for standard builds.

## Vendoring Roles (manual / offline)

```bash
# Ubuntu 22.04 CIS
ansible-galaxy install -p ansible/roles ansible-lockdown.ubuntu22_cis

# Rocky Linux 9 CIS (Rocky and RHEL 9 share the same role)
ansible-galaxy install -p ansible/roles ansible-lockdown.rhel9_cis

# RHEL 8 STIG
ansible-galaxy install -p ansible/roles ansible-lockdown.rhel8_stig
```

Or install all at once:

```bash
ansible-galaxy install -r ansible/requirements.yml -p ansible/roles
```

## Expected Structure

```
ansible/
├── site.yml          # Top-level playbook (OS-detecting, auto-selects role)
├── requirements.yml  # Galaxy role dependencies
└── roles/
    ├── UBUNTU22-CIS/ # Vendored role
    └── ROCKY9-CIS/   # etc.
```

## Example `site.yml`

```yaml
---
- name: Apply CIS hardening
  hosts: all
  become: true
  vars:
    ubuntu22cis_level1: true
    ubuntu22cis_level2: false
  roles:
    - role: UBUNTU22-CIS
```

Stratum generates this playbook dynamically from your blueprint's `hardening.profile_tier` and `hardening.overrides` fields. You rarely need to edit `site.yml` directly.

## Profile Tier Variable Mapping

| Blueprint tier | Ansible vars injected |
|---|---|
| `cis-l1` | `*cis_level1: true`, `*cis_level2: false` |
| `cis-l2` | `*cis_level1: true`, `*cis_level2: true` |
| `stig` | `*cis_level1: true`, `*cis_level2: true`, `*stig: true` |
| `custom` | only `overrides` entries applied |

## Running Manually

```bash
ansible-playbook -i "192.168.1.10," ansible/site.yml -u root
```

Stratum's providers call `ansible-playbook` automatically during the build pipeline via `_provider_utils.run_ansible()`. See `plugins/providers/example_local.py` for reference.

## In the Build Pipeline

```
Stratum Blueprint YAML
        │
        ▼ playbook_gen.py generates site.yml
        ▼ provider calls ansible-playbook via SSH / SSM
        ▼ OpenSCAP scan runs after hardening
        ▼ Instance is snapshotted as the golden image
```

After the image is built, use the **Compliance Scanner** or **Pipeline API** to verify the image score at any time — without re-running the full build.
