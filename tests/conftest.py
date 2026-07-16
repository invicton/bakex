# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Shared pytest configuration."""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Run AnyIO-marked tests on asyncio only.

    BakeX runtime code uses asyncio primitives for background webhook tasks.
    Exercising every AnyIO test under Trio duplicates the suite and creates
    false failures unrelated to the supported runtime backend.
    """
    return "asyncio"
