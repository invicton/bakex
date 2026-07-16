# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Static checks for public cloud onboarding templates."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

ROOT = Path(__file__).parent.parent


class CfnLoader(yaml.SafeLoader):
    pass


def _cfn(loader, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


for _tag in ("!Ref", "!Sub", "!GetAtt", "!Equals", "!If"):
    CfnLoader.add_constructor(_tag, _cfn)


def test_aws_onboarding_templates_have_external_id_default():
    for relpath in (
        "deploy/aws/statim-scanner-role.yaml",
        "deploy/aws/statim-builder-role.yaml",
    ):
        data = yaml.load((ROOT / relpath).read_text(), Loader=CfnLoader)
        trusted_principal = data["Parameters"]["TrustedPrincipalArn"]
        external_id = data["Parameters"]["ExternalId"]
        assert trusted_principal["Default"] == ""
        assert "root" in trusted_principal["AllowedPattern"]
        assert "UseDefaultTrustedPrincipal" in data["Conditions"]
        assert external_id["MinLength"] == 8
        assert len(external_id["Default"]) >= 8
        assert {"StatimRoleArn", "ExternalId", "InstanceProfileName", "RegionHint"} <= set(data["Outputs"])


def test_azure_onboarding_templates_have_required_shape():
    for relpath in (
        "deploy/azure/statim-scanner-role.json",
        "deploy/azure/statim-builder-role.json",
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
        role = yaml.safe_load((module_dir / f"statim-{module}-role.yaml").read_text())

        assert "gcloud services enable compute.googleapis.com iap.googleapis.com" in script
        assert "gcloud iam roles create" in script
        assert "gcloud projects add-iam-policy-binding" in script
        assert "statim-allow-iap-ssh" in script
        assert {"title", "description", "includedPermissions"} <= set(role)
        assert expected_permissions[module] <= set(role["includedPermissions"])
