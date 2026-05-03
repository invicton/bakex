# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Runtime provider registry (singleton)."""

from __future__ import annotations

import threading
from pathlib import Path

from stratum.plugins.base_provider import BaseProvider
from stratum.plugins.loader import load_providers


class ProviderRegistry:
    """Singleton that holds the loaded provider map."""

    _instance: ProviderRegistry | None = None
    _class_lock: threading.Lock = threading.Lock()

    def __new__(cls) -> ProviderRegistry:
        with cls._class_lock:
            if cls._instance is None:
                inst = super().__new__(cls)
                inst._providers = {}
                inst._lock = threading.Lock()
                cls._instance = inst
        return cls._instance

    def load(self, plugins_dir: Path, strict: bool = True) -> list[str]:
        """Discover providers and populate the registry.

        Returns:
            List of non-fatal warning strings (e.g. name collisions).
        """
        providers, warnings = load_providers(plugins_dir, strict=strict)
        with self._lock:
            self._providers = providers
        return warnings

    def get(self, name: str) -> type[BaseProvider]:
        with self._lock:
            if name not in self._providers:
                available = list(self._providers)
            else:
                return self._providers[name]
        raise KeyError(f"Provider '{name}' is not registered. Available: {available}")

    def all(self) -> dict[str, type[BaseProvider]]:
        with self._lock:
            return dict(self._providers)

    def names(self) -> list[str]:
        with self._lock:
            return sorted(self._providers)


registry = ProviderRegistry()
