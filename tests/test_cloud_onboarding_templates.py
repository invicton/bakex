# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Static checks for public cloud onboarding templates."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent


def test_azure_onboarding_templates_have_required_shape():
    for relpath in (
        "deploy/azure/stratum-scanner-role.json",
        "deploy/azure/stratum-builder-role.json",
    ):
        data = json.loads((ROOT / relpath).read_text())
        assert data["$schema"].endswith("subscriptionDeploymentTemplate.json#")
        assert {"principalObjectId", "resourceGroupName", "location"} <= set(data["parameters"])
        resource_types = {resource["type"] for resource in data["resources"]}
        assert "Microsoft.Authorization/roleDefinitions" in resource_types
        assert "Microsoft.Authorization/roleAssignments" in resource_types
        assert {"SubscriptionId", "ResourceGroupName", "Location"} <= set(data["outputs"])


def test_gcp_onboarding_scripts_and_roles_have_required_shape():
    expected_permissions = {
        "builder": {
            "compute.instances.create",
            "compute.instances.stop",
            "compute.images.create",
            "compute.globalOperations.get",
            "compute.subnetworks.use",
        },
        "scanner": {
            "compute.instances.create",
            "compute.instances.delete",
            "compute.images.getFromFamily",
            "compute.zoneOperations.get",
            "compute.subnetworks.use",
        },
    }

    for module in ("scanner", "builder"):
        module_dir = ROOT / "deploy" / "gcp" / module
        script = (module_dir / "onboard.sh").read_text()
        role = yaml.safe_load((module_dir / f"stratum-{module}-role.yaml").read_text())

        assert "gcloud services enable compute.googleapis.com iap.googleapis.com" in script
        assert "gcloud iam roles create" in script
        assert "gcloud projects add-iam-policy-binding" in script
        assert "stratum-allow-iap-ssh" in script
        assert {"title", "description", "includedPermissions"} <= set(role)
        assert expected_permissions[module] <= set(role["includedPermissions"])
