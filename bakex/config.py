# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

from bakex import paths


class Settings(BaseSettings):
    app_name: str = "BakeX"
    plugins_dir: Path = Path("plugins/providers")
    catalog_dir: Path = Path("plugins/catalog")
    profiles_dir: Path = Path("profiles")
    user_profiles_dir: Path = Path("profiles/user")
    data_dir: Path = Path("data")
    bakex_secret_key: str | None = None
    bakex_admin_token: str | None = None
    bakex_agent_require_confirmation: bool = True
    debug: bool = False
    strict_plugins: bool = True
    registry_url: str = "https://raw.githubusercontent.com/bakex/BakeX/main/blueprints"

    # Blueprint Registry — S3 private/enterprise store
    blueprint_store_s3_bucket: str = ""
    blueprint_store_s3_prefix: str = "blueprints/"
    blueprint_store_s3_region: str = "us-east-1"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    def model_post_init(self, context: Any) -> None:
        # Pip installs run from arbitrary CWDs where the repo-relative defaults
        # don't exist; fall back to the read-only copies bundled in the wheel.
        # Explicitly configured dirs (init kwarg or env var) are never swapped.
        if "profiles_dir" not in self.model_fields_set and not self.profiles_dir.is_dir():
            bundled = paths.BUNDLED_DIR / "profiles"
            if bundled.is_dir():
                self.profiles_dir = bundled
        if "catalog_dir" not in self.model_fields_set and not self.catalog_dir.is_dir():
            bundled = paths.BUNDLED_DIR / "plugins" / "catalog"
            if bundled.is_dir():
                self.catalog_dir = bundled

    @property
    def plugins_dir_absolute(self) -> Path:
        """Return plugins_dir resolved to an absolute path (cwd-independent)."""
        return self.plugins_dir.resolve()

    @property
    def catalog_dir_absolute(self) -> Path:
        """Return catalog_dir resolved to an absolute path (cwd-independent)."""
        return self.catalog_dir.resolve()


settings = Settings()
