"""Application settings; all development data stays under a dedicated root/database."""

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, YamlConfigSettingsSource

ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="MEETING_APP_", extra="ignore", yaml_file=ROOT / "configs/backend.yaml"
    )
    mongo_uri: str = "mongodb://127.0.0.1:27017"
    mongo_database: str = "meeting_app_dev"
    data_dir: Path = ROOT / "data/app"
    pipeline_config: Path = ROOT / "configs/default.yaml"
    model_cache_dir: Path = ROOT / "data/model_cache"
    web_dist: Path = ROOT / "apps/web/dist"
    session_hours: int = Field(24, ge=1, le=720)
    cookie_secure: bool = False
    max_upload_bytes: int = Field(1_000_000_000, ge=1024)
    max_sources: int = Field(8, ge=1, le=8)
    lease_seconds: int = Field(90, ge=15)
    allowed_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        return (
            init_settings,
            env_settings,
            YamlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )

    @field_validator("mongo_database")
    @classmethod
    def dedicated_database(cls, value: str) -> str:
        if not value.startswith("meeting_app_") or any(c in value for c in '/\\. "$'):
            raise ValueError("Database ứng dụng phải có prefix meeting_app_.")
        return value

    @field_validator("data_dir", "model_cache_dir", "pipeline_config", "web_dist")
    @classmethod
    def absolute_path(cls, value: Path) -> Path:
        value = value.expanduser()
        return value.absolute() if value.is_absolute() else (ROOT / value).absolute()
