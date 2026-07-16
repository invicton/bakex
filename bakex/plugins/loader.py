# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Hybrid provider loader: entry_points (pip-installed) + drop-in directory."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import inspect
import logging
from pathlib import Path

from bakex.plugins.base_provider import BaseProvider
from bakex.plugins.subprocess_provider import SUBPROCESS_SENTINEL, make_subprocess_provider_class

logger = logging.getLogger(__name__)


def load_providers(
    plugins_dir: Path,
    strict: bool = True,
) -> tuple[dict[str, type[BaseProvider]], list[str]]:
    """Discover and return all registered BaseProvider subclasses.

    Resolution order (later entries win on name collision):
    1. pip entry_points in group ``bakex.providers``
    2. Drop-in ``*.py`` files inside ``plugins_dir``

    Returns:
        (providers, warnings) where warnings is a list of non-fatal messages
        (e.g. name collisions).  If strict=True, raises RuntimeError when any
        plugin fails to load instead of silently skipping it.
    """
    providers: dict[str, type[BaseProvider]] = {}
    errors: list[str] = []
    warnings: list[str] = []

    # 1. Load from pip-installed packages via entry_points
    try:
        eps = importlib.metadata.entry_points(group="bakex.providers")
        for ep in eps:
            try:
                cls = ep.load()
                _validate_provider(cls)
                if cls.name in providers:
                    msg = f"Provider '{cls.name}' overridden by entry_point {ep.name} (was {providers[cls.name]})"
                    logger.warning(msg)
                    warnings.append(msg)
                providers[cls.name] = cls
                logger.info("Loaded entry_point provider: %s → %s", cls.name, cls)
            except Exception as exc:
                msg = f"entry_point {ep.name}: {exc}"
                logger.error("Failed to load entry_point %s: %s", ep.name, exc)
                errors.append(msg)
    except Exception as exc:
        msg = f"Could not query entry_points: {exc}"
        logger.error(msg)
        errors.append(msg)

    # 2. Load from drop-in .py files
    if plugins_dir.is_dir():
        for py_file in sorted(plugins_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                if spec is None or spec.loader is None:
                    continue
                mod = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                if _is_subprocess_script(mod):
                    provider_name = getattr(mod, SUBPROCESS_SENTINEL)
                    cls = make_subprocess_provider_class(py_file.resolve(), provider_name)
                    if provider_name in providers:
                        msg = f"Provider '{provider_name}' overridden by subprocess drop-in {py_file.name} (was {providers[provider_name]})"
                        logger.warning(msg)
                        warnings.append(msg)
                    providers[provider_name] = cls
                    logger.info(
                        "Loaded subprocess provider: %s → %s (%s)",
                        provider_name,
                        cls,
                        py_file.name,
                    )
                    continue
                for attr in vars(mod).values():
                    if not _is_concrete_provider_candidate(attr):
                        continue
                    try:
                        _validate_provider(attr)
                    except TypeError as exc:
                        msg = f"drop-in {py_file.name}: {exc}"
                        logger.error(msg)
                        errors.append(msg)
                        continue
                    if attr.name in providers:
                        msg = (
                            f"Provider '{attr.name}' overridden by drop-in {py_file.name} (was {providers[attr.name]})"
                        )
                        logger.warning(msg)
                        warnings.append(msg)
                    providers[attr.name] = attr
                    logger.info("Loaded drop-in provider: %s → %s", attr.name, attr)
            except Exception as exc:
                msg = f"drop-in {py_file.name}: {exc}"
                logger.error("Failed to load drop-in plugin %s: %s", py_file.name, exc)
                errors.append(msg)
    else:
        logger.debug("plugins_dir %s does not exist — skipping drop-in loading", plugins_dir)

    if errors and strict:
        raise RuntimeError("Plugin loading failed:\n" + "\n".join(errors))

    return providers, warnings


def _is_subprocess_script(mod) -> bool:
    """Return True if *mod* is a subprocess provider script (has PROVIDER_NAME sentinel)."""
    return isinstance(getattr(mod, SUBPROCESS_SENTINEL, None), str)


def _validate_provider(cls: object) -> None:
    """Raise TypeError if cls is not a fully-implemented concrete BaseProvider."""
    if not (isinstance(cls, type) and issubclass(cls, BaseProvider) and cls is not BaseProvider):
        raise TypeError(f"{cls!r} is not a BaseProvider subclass")
    if not (hasattr(cls, "name") and isinstance(getattr(cls, "name", None), str)):
        raise TypeError(f"{cls!r} is missing a string class attribute 'name'")
    abstract = {name for name, val in inspect.getmembers(cls) if getattr(val, "__isabstractmethod__", False)}
    if abstract:
        raise TypeError(f"{cls!r} has unimplemented abstract methods: {abstract}")


def _is_concrete_provider_candidate(obj: object) -> bool:
    """Return True if obj looks like it could be a BaseProvider subclass (pre-validation filter)."""
    return isinstance(obj, type) and issubclass(obj, BaseProvider) and obj is not BaseProvider


# Backwards-compatible helper kept for existing tests that import it directly
def _is_valid_provider(obj: object) -> bool:
    """Return True if obj is a concrete BaseProvider subclass with a name."""
    try:
        _validate_provider(obj)
        return True
    except TypeError:
        return False
