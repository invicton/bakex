# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Tombstone for the former ``stratum`` module.

Stratum was renamed to BakeX at v0.6.0. This module exists only so that stale
``import stratum`` code fails with a message that says what to do, rather than a bare
``ModuleNotFoundError`` after the real package disappeared out from under it.

Importing the module raises; installing the distribution does not, and it pulls in
``bakex`` so the tool itself is still there.
"""

raise ImportError(
    "The 'stratum' module was renamed to 'bakex' in v0.6.0 — use 'import bakex' instead.\n"
    "\n"
    "The 'stratumoss' distribution is a tombstone and is no longer developed. Depend on\n"
    "'bakex' directly:\n"
    "\n"
    "    pip uninstall stratumoss\n"
    "    pip install bakex\n"
    "\n"
    "Also rename STRATUM_* environment variables to BAKEX_*, and the 'stratum_version'\n"
    "field in any blueprint YAML to 'bakex_version'.\n"
    "\n"
    "Details: https://github.com/invicton/bakex/blob/main/CHANGELOG.md"
)
