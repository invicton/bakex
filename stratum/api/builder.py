# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Image build trigger + status API endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import HTMLResponse, Response

from stratum.config import settings
from stratum.core import builder as build_service
from stratum.core.blueprint import list_profiles, load_profile

router = APIRouter(prefix="/api/builder", tags=["builder"])

_RESULTS_DIR = Path("data/builds")


@router.post("/start")
async def start_build(request: Request, background_tasks: BackgroundTasks):
    """Trigger a new image build job. Returns an HTMX redirect.

    Accepts two submission modes:
    - Wizard mode: form contains ``wizard_os`` and ``wizard_provider``
    - Legacy mode: form contains ``profile_name``
    """
    form = await request.form()

    # ---- Wizard submission path ----
    wizard_os = form.get("wizard_os", "")
    if wizard_os:
        profile = _build_profile_from_wizard(form)
        provider_override = None
    else:
        # ---- Legacy profile-based path ----
        profile_name = str(form.get("profile_name", ""))
        if not profile_name:
            raise HTTPException(status_code=400, detail="profile_name is required")
        provider_override = form.get("provider_override")

        profile = _resolve_profile(profile_name)
        if provider_override:
            profile.target.provider = str(provider_override)

    if form.get("root_volume_size_gb"):
        profile.target.root_volume_size_gb = int(form["root_volume_size_gb"])

    # Process custom partitions
    import math

    from stratum.core.blueprint import ExtraVolume, MountEntry

    # Check if we have any custom partitions submitted (indicated by presence of extra_vol_*_mount)
    custom_part_keys = [k for k in form.keys() if k.startswith("extra_vol_") and k.endswith("_mount")]

    if custom_part_keys or form.get("custom_layout_active") == "true":
        new_extras = []
        new_mounts = []

        # Keep tmpfs mounts from the blueprint
        for m in profile.filesystem:
            if m.fstype == "tmpfs":
                new_mounts.append(m)

        # Sort by key index logic (extra_vol_0_..., extra_vol_1_...)
        for idx_int, key in enumerate(sorted(custom_part_keys)):
            idx = key.split("_")[2]

            # Auto-generate device mapping for AWS
            ebs_dev = f"/dev/sd{chr(ord('f') + idx_int)}"
            os_dev = f"/dev/nvme{idx_int + 1}n1"

            unit = form.get(f"extra_vol_{idx}_unit", "GB")
            raw_size_str = form.get(f"extra_vol_{idx}_size", "2")
            try:
                raw_size = float(raw_size_str)
            except ValueError:
                raw_size = 2.0

            if unit == "TB":
                size_gb = int(math.ceil(raw_size * 1024))
            elif unit == "MB":
                size_gb = int(math.ceil(raw_size / 1024))
                if size_gb < 1:
                    size_gb = 1
            else:
                size_gb = int(math.ceil(raw_size))

            mount = form.get(key)
            fstype = form.get(f"extra_vol_{idx}_fstype", "xfs")

            if mount:
                new_extras.append(ExtraVolume(device_name=ebs_dev, size_gb=size_gb))
                new_mounts.append(MountEntry(device=os_dev, mountpoint=mount, fstype=fstype, options=["defaults"]))

        profile.target.extra_volumes = new_extras
        profile.filesystem = new_mounts

    from stratum.api.integrations import get_credentials as _get_creds

    _creds = _get_creds(profile.target.provider) or {}
    job = build_service.BuildJob(
        profile_name=profile.metadata.name,
        provider_name=profile.target.provider,
        base_image=profile.target.base_image or "",
        region=_creds.get("region", "us-east-1"),
        instance_type=profile.target.instance_type or "t3.medium",
        subnet_id=_creds.get("subnet_id", ""),
    )
    build_service._jobs[job.id] = job

    background_tasks.add_task(build_service.run_build, profile, _RESULTS_DIR, job)
    return Response(headers={"HX-Redirect": f"/builder/run/{job.id}"})


@router.get("/os-catalog")
async def os_catalog_endpoint() -> dict:
    """Return OS list with provider compatibility for the wizard Step 1."""
    from stratum.core.os_catalog import OS_CATALOG, PROVIDER_CATALOG

    return {
        "os_list": [
            {
                "slug": slug,
                "display": data["display"],
                "icon": data.get("icon", "🐧"),
                "providers": data["providers"],
                "min_root_gb": data["min_root_gb"],
                "supported_tiers": data["supported_tiers"],
                "selinux": data.get("selinux", False),
            }
            for slug, data in OS_CATALOG.items()
        ],
        "provider_catalog": PROVIDER_CATALOG,
    }


@router.get("/instance-types")
async def get_instance_types(provider: str = "") -> dict:
    """Return suggested instance types for a given provider."""
    from stratum.core.os_catalog import INSTANCE_TYPES

    return {"types": INSTANCE_TYPES.get(provider, [])}


@router.get("/resolve-image")
async def resolve_image(os: str = "", provider: str = "aws", region: str = "us-east-1") -> dict:
    """Resolve the latest base image ID for the given OS, provider, and region.

    For AWS: calls describe_images in the target region using owner+name filters.
    For GCP/Azure/DigitalOcean/Linode: returns the static catalog value (image
    families and slugs are already self-updating).

    Returns: {"ami_id": "...", "region": "...", "source": "resolved"|"catalog"}
    """
    from stratum.core.os_catalog import OS_CATALOG

    os_data = OS_CATALOG.get(os, {})
    fallback = os_data.get("default_base_image", {}).get(provider, "")

    if provider != "aws":
        return {"ami_id": fallback, "region": region, "source": "catalog"}

    # Call the AWS subprocess provider's resolve_image RPC
    from stratum.api.integrations import get_credentials as _get_creds
    from stratum.plugins.registry import registry

    creds = _get_creds("aws") or {}
    creds["region"] = region  # honour the requested region, not the stored default

    try:
        provider_cls = registry.get("aws")
        prov = provider_cls()
        result = prov._call_rpc(
            "resolve_image",
            {  # type: ignore[attr-defined]
                "credentials": creds,
                "os": os,
                "fallback": fallback,
            },
        )
        return {"ami_id": result.get("ami_id", fallback), "region": region, "source": "resolved"}
    except Exception as exc:
        return {"ami_id": fallback, "region": region, "source": "fallback", "error": str(exc)}


@router.get("/cis-layout")
async def get_cis_layout(os: str = "") -> HTMLResponse:
    """Return pre-populated partition rows for 'Apply CIS Standard Layout'."""
    from stratum.core.os_catalog import CIS_STANDARD_LAYOUT

    rows_html = ""
    for i, entry in enumerate(CIS_STANDARD_LAYOUT):
        mount = entry["mountpoint"]
        fstype = entry["fstype"]
        size_gb = entry["size_gb"]
        opts = ",".join(entry["options"])
        rows_html += f"""
        <div class="flex gap-2 items-end border border-slate-700/60 p-3 rounded-lg bg-slate-900/40 hover:border-cyan-500/20 transition-all" data-part-row data-part-idx="{i}">
          <div class="flex-1 grid grid-cols-12 gap-2">
            <div class="col-span-4">
              <select name="extra_vol_{i}_mount" class="mountpoint-select w-full text-xs font-mono bg-slate-950 border border-slate-800 rounded px-2 py-1.5 text-slate-300 focus:border-cyan-500 focus:outline-none" onchange="onMountChange(this, {i})">
                <optgroup label="CIS Required">
                  <option value="/var" {"selected" if mount == "/var" else ""}>/var</option>
                  <option value="/var/log" {"selected" if mount == "/var/log" else ""}>/var/log</option>
                  <option value="/var/log/audit" {"selected" if mount == "/var/log/audit" else ""}>/var/log/audit</option>
                  <option value="/home" {"selected" if mount == "/home" else ""}>/home</option>
                  <option value="/tmp" {"selected" if mount == "/tmp" else ""}>/tmp</option>
                  <option value="/var/tmp" {"selected" if mount == "/var/tmp" else ""}>/var/tmp</option>
                  <option value="/opt" {"selected" if mount == "/opt" else ""}>/opt</option>
                </optgroup>
                <optgroup label="Other Standard">
                  <option value="/boot/efi">/boot/efi</option>
                  <option value="swap">swap</option>
                </optgroup>
                <option value="__custom__">Custom path...</option>
              </select>
              <input type="text" name="extra_vol_{i}_mount_custom" class="mountpoint-custom hidden w-full text-xs font-mono bg-slate-950 border border-cyan-500 rounded px-2 py-1.5 text-slate-300 focus:outline-none mt-1" placeholder="/mnt/data">
            </div>
            <div class="col-span-2">
              <select name="extra_vol_{i}_fstype" class="fstype-select w-full text-xs font-mono bg-slate-950 border border-slate-800 rounded px-2 py-1.5 text-slate-300 focus:border-cyan-500 focus:outline-none">
                <option value="xfs" {"selected" if fstype == "xfs" else ""}>xfs</option>
                <option value="ext4" {"selected" if fstype == "ext4" else ""}>ext4</option>
                <option value="ext3" {"selected" if fstype == "ext3" else ""}>ext3</option>
                <option value="ext2" {"selected" if fstype == "ext2" else ""}>ext2</option>
                <option value="btrfs" {"selected" if fstype == "btrfs" else ""}>btrfs</option>
                <option value="vfat" {"selected" if fstype == "vfat" else ""}>vfat</option>
                <option value="tmpfs" {"selected" if fstype == "tmpfs" else ""}>tmpfs</option>
              </select>
            </div>
            <div class="col-span-2">
              <input type="number" name="extra_vol_{i}_size" value="{size_gb}" min="1" step="1"
                     class="w-full text-xs font-mono bg-slate-950 border border-slate-800 rounded px-2 py-1.5 text-slate-300 focus:border-cyan-500 focus:outline-none" onchange="updateBudget()">
            </div>
            <div class="col-span-1">
              <select name="extra_vol_{i}_unit" class="w-full text-xs font-mono bg-slate-950 border border-slate-800 rounded p-[5px] pb-[7px] text-slate-300 focus:border-cyan-500 focus:outline-none" onchange="updateBudget()">
                <option value="GB" selected>GB</option>
                <option value="MB">MB</option>
                <option value="TB">TB</option>
              </select>
            </div>
            <div class="col-span-3">
              <div class="flex gap-1 flex-wrap pt-1" id="opts-{i}">
                {"".join(f'<button type="button" data-opt="{o}" data-row-idx="{i}" data-active="1" onclick="toggleOpt(this,{i})" class="opt-chip px-2 py-0.5 rounded text-[10px] font-mono font-bold border border-cyan-500/60 bg-cyan-950/20 text-cyan-300 transition-all">{o}</button>' if o not in ("defaults", "rw", "relatime") else "" for o in opts.split(","))}
              </div>
              <input type="hidden" name="extra_vol_{i}_options" id="opts-val-{i}" value="{opts}">
            </div>
          </div>
          <button type="button" onclick="removePartition(this)" class="flex-shrink-0 text-slate-500 hover:text-rose-400 p-1.5 rounded bg-slate-950 border border-slate-800 hover:border-rose-900/50 hover:bg-rose-950/30 transition-colors mb-0.5">
            <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
          </button>
        </div>"""
    if not rows_html:
        rows_html = '<p class="text-xs text-slate-500 italic">No partitions in layout.</p>'
    return HTMLResponse(content=rows_html)


@router.get("/controls")
async def get_controls(
    os: str = "",
    standard: str = "cis",
    tier: str = "l1",
) -> HTMLResponse:
    """Return the searchable controls table fragment for wizard Step 4."""
    from stratum.core.os_catalog import CIS_CONTROLS

    tier_key = f"{standard}-{tier}"
    controls = CIS_CONTROLS.get(os, {}).get(tier_key, [])

    if not controls:
        return HTMLResponse(
            content='<p class="text-xs text-slate-500 italic py-4 text-center">'
            "No controls catalog available for this OS/tier combination.<br>"
            "Controls will be applied by the Ansible-Lockdown role at build time.</p>"
        )

    sev_badge = {
        "critical": "text-rose-400 bg-rose-950/40 border border-rose-800/40",
        "high": "text-orange-400 bg-orange-950/40 border border-orange-800/40",
        "medium": "text-amber-400 bg-amber-950/40 border border-amber-800/40",
        "low": "text-blue-400 bg-blue-950/40 border border-blue-800/40",
    }

    # Group by section prefix from title (e.g. "1.1", "3.2", "STIG")
    from collections import OrderedDict

    sections: dict[str, list] = OrderedDict()
    for ctrl in controls:
        title = ctrl["title"]
        # Extract section number from leading digits like "1.1.4" or "STIG"
        parts = title.split(" ", 1)
        sec_key = parts[0] if parts[0][0].isdigit() or parts[0] == "STIG" else "Other"
        # Collapse to top-level section (first digit group before second dot)
        dots = sec_key.split(".")
        sec = dots[0] if len(dots) >= 1 else sec_key
        sections.setdefault(sec, []).append(ctrl)

    section_labels = {
        "1": "§1 — Initial Setup",
        "2": "§2 — Services",
        "3": "§3 — Network Configuration",
        "4": "§4 — Logging & Auditing",
        "5": "§5 — Access, Auth & Authorization",
        "6": "§6 — System Maintenance",
        "STIG": "STIG — Additional Controls",
        "Other": "Other",
    }

    rows = ""
    for sec, ctrls in sections.items():
        label = section_labels.get(sec, f"Section {sec}")
        sec_enabled = sum(1 for c in ctrls if c.get("enabled", True))
        rows += f"""
        <tr class="section-header-row bg-slate-900/70">
          <td colspan="3" class="py-1.5 pl-3 pr-3">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-bold uppercase text-cyan-600 tracking-widest">{label}</span>
              <span class="text-[10px] text-slate-500">{sec_enabled}/{len(ctrls)} enabled</span>
            </div>
          </td>
        </tr>"""
        for ctrl in ctrls:
            rule_id = ctrl["id"]
            title = ctrl["title"]
            severity = ctrl.get("severity", "medium")
            enabled = ctrl.get("enabled", True)
            badge_cls = sev_badge.get(severity, sev_badge["medium"])
            short_id = rule_id.split("content_rule_")[-1] if "content_rule_" in rule_id else rule_id

            rows += f"""
        <tr class="control-row border-b border-slate-800/40 hover:bg-slate-800/20 transition-colors"
            data-rule-id="{short_id}" data-rule-title="{title.lower()}" data-severity="{severity}">
          <td class="py-2 pl-3 pr-2 w-10">
            <input type="checkbox" name="control_{rule_id}" {"checked" if enabled else ""}
                   class="control-toggle w-4 h-4 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-0 cursor-pointer"
                   onchange="onControlToggle(this, '{rule_id}')">
          </td>
          <td class="py-2 pr-3">
            <span class="text-xs text-slate-200">{title}</span>
            <div class="hidden mt-1" id="just-{short_id}">
              <input type="text" name="control_{rule_id}_justification"
                     placeholder="Justification for disabling this control..."
                     class="w-full text-[10px] font-mono bg-slate-900 border border-amber-800/50 rounded px-2 py-1 text-amber-300 focus:outline-none focus:border-amber-500">
            </div>
          </td>
          <td class="py-2 pr-3 w-20 text-right">
            <span class="text-[10px] font-bold uppercase px-1.5 py-0.5 rounded {badge_cls}">{severity}</span>
          </td>
        </tr>"""

    total = len(controls)
    enabled_count = sum(1 for c in controls if c.get("enabled", True))

    html = f"""
    <div class="space-y-3">
      <div class="flex items-center gap-2 flex-wrap">
        <input type="text" id="controls-search" placeholder="Search controls…"
               oninput="filterControls(this.value)"
               class="flex-1 min-w-48 text-xs bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-slate-300 focus:outline-none focus:border-cyan-500 font-mono">
        <select id="severity-filter" onchange="filterBySeverity(this.value)"
                class="text-xs bg-slate-900 border border-slate-700 rounded-lg px-2 py-1.5 text-slate-300 focus:outline-none focus:border-cyan-500">
          <option value="">All severities</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <span class="text-xs text-slate-400 whitespace-nowrap">
          <span id="controls-enabled-count">{enabled_count}</span> of <span id="controls-total">{total}</span> enabled
        </span>
      </div>
      <div class="rounded-lg border border-slate-800 overflow-hidden max-h-[480px] overflow-y-auto">
        <table class="w-full text-sm">
          <thead class="sticky top-0 z-10">
            <tr class="bg-slate-900 border-b border-slate-800">
              <th class="py-2 pl-3 pr-2 w-10 text-left">
                <input type="checkbox" id="toggle-all-controls" checked
                       onchange="toggleAllControls(this)"
                       class="w-4 h-4 rounded border-slate-700 bg-slate-900 text-cyan-500 focus:ring-0 cursor-pointer"
                       title="Toggle all">
              </th>
              <th class="py-2 pr-3 text-left text-[10px] font-bold uppercase text-slate-500 tracking-wider">Control</th>
              <th class="py-2 pr-3 w-20 text-right text-[10px] font-bold uppercase text-slate-500 tracking-wider">Severity</th>
            </tr>
          </thead>
          <tbody id="controls-tbody">
            {rows}
          </tbody>
        </table>
      </div>
      <script>
      function filterBySeverity(sev) {{
        const q = document.getElementById('controls-search')?.value || '';
        document.querySelectorAll('.control-row').forEach(row => {{
          const matchSev = !sev || row.dataset.severity === sev;
          const matchQ = !q || row.dataset.ruleId?.includes(q.toLowerCase()) || row.dataset.ruleTitle?.includes(q.toLowerCase());
          row.style.display = (matchSev && matchQ) ? '' : 'none';
        }});
      }}
      </script>
    </div>"""
    return HTMLResponse(content=html)


@router.get("/profile-fields")
async def get_profile_fields(profile_name: str) -> HTMLResponse:
    try:
        profile = _resolve_profile(profile_name)
    except HTTPException:
        return HTMLResponse(content="")

    js_prefills = []

    # Simple heuristic to match extra_volumes with filesystem mounts sequentially
    block_mounts = [m for m in profile.filesystem if m.fstype != "tmpfs"]
    for i, ev in enumerate(profile.target.extra_volumes):
        if i < len(block_mounts):
            m = block_mounts[i]
            js_prefills.append(f"{{ size: {ev.size_gb}, mount: '{m.mountpoint}', fstype: '{m.fstype}' }}")

    prefill_array = "[ " + ", ".join(js_prefills) + " ]"

    content = f"""
    <div class="space-y-5 pt-4 border-t border-slate-800/60 mt-6" id="fs-builder">
      <div class="flex items-center justify-between">
        <h3 class="text-sm font-semibold text-brand-400 flex items-center gap-2"><span class="text-lg">💽</span> Filesystem Layout</h3>
      </div>
      
      <div>
        <label class="block text-xs font-semibold text-slate-400 mb-1.5 uppercase tracking-wide">Root Volume Size (GB)</label>
        <input type="number" name="root_volume_size_gb" value="{profile.target.root_volume_size_gb}" required min="1"
               class="w-full bg-slate-900/50 border border-slate-700/80 rounded-lg px-4 py-2.5 text-sm text-white focus:outline-none focus:ring-2 focus:ring-brand-500/50 focus:border-brand-500 transition-all font-mono">
      </div>

      <div class="mt-4 p-4 rounded-xl border border-brand-900/30 bg-brand-950/10">
        <div class="flex items-center justify-between mb-4">
          <label class="block text-xs font-semibold text-brand-300 uppercase tracking-wide">Custom Partitions</label>
          <button type="button" onclick="addPartition()" class="text-xs bg-brand-600 hover:bg-brand-500 text-white font-medium px-3 py-1.5 rounded-md transition-all shadow-sm flex items-center gap-1.5">
            <svg class="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M12 4v16m8-8H4"></path></svg> Add Partition
          </button>
        </div>
        
        <input type="hidden" name="custom_layout_active" value="true">
        
        <div id="partitions-container" class="space-y-3">
          <!-- Rows injected via JS -->
        </div>
        <p id="no-parts-msg" class="text-xs text-slate-500 italic mt-3 hidden">Single root filesystem selected. No extra partitions will be created.</p>
      </div>
    """

    content += f"""
      <script>
        var partCount = 0;
        function updateNoPartsMsg() {{
            const container = document.getElementById('partitions-container');
            if (container.children.length === 0) {{
                document.getElementById('no-parts-msg').classList.remove('hidden');
            }} else {{
                document.getElementById('no-parts-msg').classList.add('hidden');
            }}
        }}

        function addPartition(data = null) {{
          const size = data ? data.size : '2';
          const mount = data ? data.mount : '/var';
          const fstype = data ? data.fstype : 'xfs';
          const unit = 'GB';
          
          const html = `
            <div class="flex gap-3 items-start border border-slate-700/60 p-3 rounded-lg bg-slate-900/40 relative group transition-all hover:border-brand-500/30" id="part-${{partCount}}">
              <div class="flex-1 space-y-3">
                <div class="grid grid-cols-2 gap-3">
                    <div>
                      <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1 tracking-wider">Mount Point</label>
                      <input type="text" name="extra_vol_${{partCount}}_mount" value="${{mount}}" placeholder="/usr/local" required class="w-full text-xs font-mono bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-300 focus:border-brand-500 focus:outline-none">
                    </div>
                </div>
                <div class="grid grid-cols-3 gap-3">
                    <div class="col-span-1">
                      <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1 tracking-wider">FS Type</label>
                      <input type="text" name="extra_vol_${{partCount}}_fstype" value="${{fstype}}" placeholder="xfs" required class="w-full text-xs font-mono bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-300 focus:border-brand-500 focus:outline-none">
                    </div>
                    <div class="col-span-1 flex gap-2 items-end">
                      <div class="flex-1">
                        <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1 tracking-wider">Size</label>
                        <input type="number" name="extra_vol_${{partCount}}_size" value="${{size}}" step="0.1" required min="0.1" class="w-full text-xs font-mono bg-slate-950 border border-slate-800 rounded px-2.5 py-1.5 text-slate-300 focus:border-brand-500 focus:outline-none">
                      </div>
                      <div class="w-16">
                        <label class="block text-[10px] uppercase font-bold text-slate-500 mb-1 tracking-wider text-transparent select-none">U</label>
                        <select name="extra_vol_${{partCount}}_unit" class="w-full text-xs font-mono bg-slate-950 border border-slate-800 rounded p-[5px] pb-1.5 text-slate-300 focus:border-brand-500 focus:outline-none">
                          <option value="MB" ${{unit === 'MB' ? 'selected' : ''}}>MB</option>
                          <option value="GB" ${{unit === 'GB' ? 'selected' : ''}}>GB</option>
                          <option value="TB" ${{unit === 'TB' ? 'selected' : ''}}>TB</option>
                        </select>
                      </div>
                    </div>
                </div>
              </div>
              <button type="button" onclick="document.getElementById('part-${{partCount}}').remove(); updateNoPartsMsg();" class="mt-5 text-slate-500 hover:text-rose-400 p-1.5 rounded bg-slate-950 border border-slate-800 hover:border-rose-900/50 hover:bg-rose-950/30 transition-colors">
                <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"></path></svg>
              </button>
            </div>
          `;
          document.getElementById('partitions-container').insertAdjacentHTML('beforeend', html);
          partCount++;
          updateNoPartsMsg();
        }}
        
        // Auto-fill from blueprint
        const prefills = {prefill_array};
        if (prefills.length > 0) {{
            prefills.forEach(p => addPartition(p));
        }}
        updateNoPartsMsg();
      </script>
    </div>
    """

    return HTMLResponse(content=content)


@router.get("/provider-fields")
async def get_provider_fields(provider_override: str | None = None) -> HTMLResponse:
    return HTMLResponse(content="")


@router.get("/jobs")
async def list_build_jobs() -> list[dict]:
    return [_job_to_dict(j) for j in build_service.list_jobs()]


@router.get("/jobs/{job_id}")
async def get_build_job(job_id: str) -> dict:
    job = build_service.get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return _job_to_dict(job)


@router.get("/jobs/{job_id}/status", response_class=HTMLResponse)
async def job_status_partial(request: Request, job_id: str):
    """HTML partial for HTMX polling — renders job_status.html fragment."""
    from fastapi.templating import Jinja2Templates

    _templates = Jinja2Templates(directory="stratum/templates")
    job = build_service.get_job(job_id)
    if job is None:
        return HTMLResponse(
            content=f'<div id="job-status" class="bg-slate-900 border border-slate-800 rounded-xl p-6 text-rose-400 text-sm">'
            f'Job <span class="font-mono">{job_id[:8]}</span> not found — it may have been lost after a server restart. '
            f'<a href="/builder" class="underline text-cyan-400">Start a new build</a>.</div>',
            status_code=200,
        )
    done = job.status in (build_service.BuildStatus.COMPLETE, build_service.BuildStatus.FAILED)
    # Expand multi-line log entries (provider stdout arrives as single strings with \n)
    expanded_log = []
    for line in job.log:
        expanded_log.extend(line.split("\n"))
    return _templates.TemplateResponse(
        request=request,
        name="partials/job_status.html",
        context={
            "request": request,
            "job": job,
            "job_id": job_id,
            "status": job.status.value,
            "log": expanded_log[-30:],
            "done": done,
        },
    )


def _build_profile_from_wizard(form) -> build_service.ComplianceProfile:
    """Construct a ComplianceProfile from wizard form data."""
    import math

    from stratum.core.blueprint import (
        ComplianceProfile,
        ComplianceSpec,
        ExtraVolume,
        HardeningConfig,
        HardeningStrategy,
        MountEntry,
        ProfileMetadata,
        RootConfig,
        SystemConfig,
        TargetSpec,
        UserAccount,
        UsersConfig,
    )
    from stratum.core.os_catalog import OS_CATALOG

    os_slug = str(form.get("wizard_os", "ubuntu22.04"))
    provider = str(form.get("wizard_provider", "aws"))
    os_data = OS_CATALOG.get(os_slug, {})
    tier = str(form.get("hardening_tier", "l1"))
    standard = str(form.get("hardening_standard", "cis"))
    tier_key = f"{standard}-{tier}"

    # SCAP fields from catalog
    benchmark = os_data.get("scap_benchmark", "")
    profile_suffix = "cis_level2_server" if tier == "l2" else "cis_level1_server"
    scap_profile = os_data.get("scap_profile_prefix", "") + profile_suffix
    datastream = os_data.get("scap_datastream", "")

    # Target spec
    instance_type = str(form.get("wizard_instance_type", "t3.medium"))
    base_image = str(form.get("wizard_base_image", ""))
    if not base_image:
        base_image = os_data.get("default_base_image", {}).get(provider, "")
    root_gb = int(form.get("root_volume_size_gb", os_data.get("min_root_gb", 20)))

    # Extra volumes from wizard partitions (same field names as legacy path)
    extra_keys = sorted([k for k in form.keys() if k.startswith("extra_vol_") and k.endswith("_mount")])
    extra_volumes = []
    filesystem = []
    for idx_int, key in enumerate(extra_keys):
        idx = key.split("_")[2]
        mount = str(form.get(key, ""))
        if mount == "__custom__":
            mount = str(form.get(f"extra_vol_{idx}_mount_custom", "")).strip()
        if not mount:
            continue
        unit = str(form.get(f"extra_vol_{idx}_unit", "GB"))
        try:
            raw = float(str(form.get(f"extra_vol_{idx}_size", "2")))
        except ValueError:
            raw = 2.0
        if unit == "TB":
            size_gb = int(math.ceil(raw * 1024))
        elif unit == "MB":
            size_gb = max(1, int(math.ceil(raw / 1024)))
        else:
            size_gb = int(math.ceil(raw))
        fstype = str(form.get(f"extra_vol_{idx}_fstype", "xfs"))
        opts_raw = str(form.get(f"extra_vol_{idx}_options", "defaults"))
        options = [o.strip() for o in opts_raw.split(",") if o.strip()]
        ebs_dev = f"/dev/sd{chr(ord('f') + idx_int)}"
        os_dev = f"/dev/nvme{idx_int + 1}n1"
        if mount != "swap":
            extra_volumes.append(ExtraVolume(device_name=ebs_dev, size_gb=size_gb))
        filesystem.append(
            MountEntry(
                device="swap" if mount == "swap" else os_dev,
                mountpoint=mount,
                fstype=fstype if mount != "swap" else "swap",
                options=options or ["defaults"],
            )
        )

    # Users
    root_lock = form.get("root_lock") == "on" or form.get("root_lock") == "true"
    user_accounts = []
    user_idx = 0
    while form.get(f"user_{user_idx}_name"):
        uname = str(form.get(f"user_{user_idx}_name", "")).strip()
        groups_raw = str(form.get(f"user_{user_idx}_groups", "")).strip()
        groups = [g.strip() for g in groups_raw.split(",") if g.strip()]
        shell = str(form.get(f"user_{user_idx}_shell", "/bin/bash"))
        ssh_key = str(form.get(f"user_{user_idx}_ssh_key", "")).strip()
        ssh_keys = [ssh_key] if ssh_key else []
        if uname:
            user_accounts.append(
                UserAccount(
                    name=uname,
                    groups=groups,
                    shell=shell,
                    ssh_authorized_keys=ssh_keys,
                )
            )
        user_idx += 1

    users_config = (
        UsersConfig(
            root=RootConfig(lock=root_lock),
            accounts=user_accounts,
        )
        if user_accounts or root_lock
        else None
    )

    # Hardening
    lockdown_role = os_data.get("lockdown_roles", {}).get(tier_key, "auto")
    aide_enabled = form.get("aide_enabled") == "on"
    fips_enabled = form.get("fips_enabled") == "on"

    # Control overrides
    controls: dict = {}
    for key in form.keys():
        if key.startswith("control_") and not key.endswith("_justification"):
            rule_id = key[len("control_") :]
            just_key = f"control_{rule_id}_justification"
            justification = str(form.get(just_key, "")).strip()
            enabled = form.get(key) == "on"
            if justification:
                from stratum.core.blueprint import ControlOverride

                controls[rule_id] = ControlOverride(enabled=enabled, justification=justification)
            else:
                controls[rule_id] = enabled

    profile_name = f"{os_slug}-{tier_key}-{provider}-wizard"
    return ComplianceProfile(
        stratum_version="0.3.0",
        kind="HardeningBlueprint",
        metadata=ProfileMetadata(
            name=profile_name,
            version="1.0.0",
            description=f"Wizard-generated: {os_slug} + {tier_key} on {provider}",
            author="wizard",
            tags=[os_slug, tier_key, provider, standard],
        ),
        target=TargetSpec(
            os=os_slug,
            provider=provider,
            base_image=base_image,
            instance_type=instance_type,
            root_volume_size_gb=root_gb,
            extra_volumes=extra_volumes,
        ),
        compliance=ComplianceSpec(
            benchmark=benchmark,
            profile=scap_profile,
            datastream=datastream,
            aide=aide_enabled,
            fips=fips_enabled,
        ),
        hardening=HardeningConfig(
            strategy=HardeningStrategy.GALAXY,
            role=lockdown_role,
            profile_tier=tier_key,
        ),
        system=SystemConfig(hostname="hardened-node", timezone="UTC", locale="en_US.UTF-8"),
        filesystem=filesystem,
        users=users_config,
        controls=controls,
    )


def _resolve_profile(name: str):
    for p in list_profiles(settings.profiles_dir):
        try:
            profile = load_profile(p)
            if profile.metadata.name == name:
                return profile
        except Exception:
            continue
    raise HTTPException(status_code=404, detail=f"Profile '{name}' not found")


def _job_to_dict(job: build_service.BuildJob) -> dict:
    return {
        "id": job.id,
        "profile_name": job.profile_name,
        "provider_name": job.provider_name,
        "status": job.status.value,
        "instance_id": job.instance_id,
        "artifact_id": job.result.artifact_id if job.result else None,
        "error": job.error,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
        "log": job.log,
    }
