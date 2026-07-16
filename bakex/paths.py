# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
"""Package-anchored filesystem paths.

Templates, static assets, and bundled read-only data ship inside the
``bakex`` package, so they must be resolved relative to the package —
never the process CWD — or a pip-installed BakeX only works when run
from a repo checkout.
"""

from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"

# Read-only data bundled into the wheel (built-in blueprint templates and
# the provider catalog). Only exists in built distributions; in a repo
# checkout the CWD-relative profiles/ and plugins/catalog/ are used instead.
BUNDLED_DIR = PACKAGE_DIR / "_bundled"
