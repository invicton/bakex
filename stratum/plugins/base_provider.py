# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Abstract base class for Stratum cloud/hypervisor providers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar

from pydantic import BaseModel

from stratum.core.blueprint import ComplianceProfile


class ProviderResult(BaseModel):
    artifact_id: str  # AMI ID, Azure image name, qcow2 filename, etc.
    artifact_type: str  # "ami" | "azure_image" | "qcow2" | "ova" …
    region: str = ""  # Cloud region (if applicable)
    metadata: dict = {}


class BaseProvider(ABC):
    """Every provider plugin must subclass this and set ``name``."""

    name: ClassVar[str]  # Unique identifier, e.g. "aws", "proxmox", "local"

    @abstractmethod
    def provision(self, profile: ComplianceProfile, **kwargs) -> str:
        """Spin up a temporary instance for hardening.

        Returns:
            instance_id: An opaque string identifying the running instance.
        """

    @abstractmethod
    def run_ansible(self, instance_id: str, profile: ComplianceProfile) -> None:
        """Apply Ansible-Lockdown hardening roles to the instance."""

    @abstractmethod
    def snapshot(self, instance_id: str, profile: ComplianceProfile) -> ProviderResult:
        """Snapshot the hardened instance into a golden image.

        Returns:
            ProviderResult with the artifact details.
        """

    @abstractmethod
    def teardown(self, instance_id: str) -> None:
        """Destroy the temporary instance unconditionally."""

    def __repr__(self) -> str:
        return f"<Provider name={self.name!r}>"
