# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Static checks for public cloud onboarding templates."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_gcp_onboarding_modules_expose_required_outputs():
    for module in ("scanner", "builder"):
        module_dir = ROOT / "deploy" / "gcp" / module
        main_tf = (module_dir / "main.tf").read_text()
        outputs_tf = (module_dir / "outputs.tf").read_text()
        variables_tf = (module_dir / "variables.tf").read_text()

        assert 'source  = "hashicorp/google"' in main_tf
        assert "google_project_iam_custom_role" in main_tf
        assert "google_project_iam_member" in main_tf
        assert "stratum-allow-iap-ssh" in main_tf
        assert 'variable "project_id"' in variables_tf
        for output_name in ("project_id", "zone", "network", "subnetwork", "service_account_email"):
            assert f'output "{output_name}"' in outputs_tf
