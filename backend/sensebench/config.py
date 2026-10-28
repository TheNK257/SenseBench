"""Runtime settings, read from `SENSEBENCH_*` environment variables or a `.env` file."""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SENSEBENCH_", env_file=".env", extra="ignore")

    data_dir: Path = Path("data")
    # localhost by default: team data never leaves the machine unless deliberately exposed
    host: str = "127.0.0.1"
    port: int = 8000
