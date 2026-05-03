# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Vamshi Krishna Santhapuri
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Stratum"
    plugins_dir: Path = Path("plugins/providers")
    catalog_dir: Path = Path("plugins/catalog")
    profiles_dir: Path = Path("profiles")
    user_profiles_dir: Path = Path("profiles/user")
    data_dir: Path = Path("data")
    stratum_secret_key: str | None = None
    debug: bool = False
    strict_plugins: bool = True
    registry_url: str = "https://raw.githubusercontent.com/stratum-community/profiles/main"

    # Blueprint Registry — S3 private/enterprise store
    blueprint_store_s3_bucket: str = ""
    blueprint_store_s3_prefix: str = "blueprints/"
    blueprint_store_s3_region: str = "us-east-1"

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    @property
    def plugins_dir_absolute(self) -> Path:
        """Return plugins_dir resolved to an absolute path (cwd-independent)."""
        return self.plugins_dir.resolve()

    @property
    def catalog_dir_absolute(self) -> Path:
        """Return catalog_dir resolved to an absolute path (cwd-independent)."""
        return self.catalog_dir.resolve()


settings = Settings()
