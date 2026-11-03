"""Where things live, the rule values, and the PII key. Loaded once per run."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CONFIG = REPO_ROOT / "config" / "pipeline.toml"
DEFAULT_ENV_FILE = REPO_ROOT / ".env"
PII_KEY_NAME = "NOVA_PII_KEY"
MIN_PII_KEY_LENGTH = 32


class MissingPiiKeyError(RuntimeError):
    """Raised before any data is touched if there is no usable PII key."""


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    pii_key: str
    config: dict

    @property
    def landing_dir(self):
        return self.data_dir / "landing"

    @property
    def warehouse_path(self):
        return self.data_dir / "warehouse" / "nova.duckdb"

    @property
    def export_dir(self):
        return self.data_dir / "exports"


def read_pii_key(env_file=DEFAULT_ENV_FILE):
    load_dotenv(env_file)
    key = os.environ.get(PII_KEY_NAME, "").strip()
    # No default key, ever: a default would quietly make every token guessable.
    if not key:
        raise MissingPiiKeyError(
            f"{PII_KEY_NAME} is not set. Copy .env.example to .env and set a random key "
            f"(python -c \"import secrets; print(secrets.token_hex(32))\").")
    if len(key) < MIN_PII_KEY_LENGTH:
        raise MissingPiiKeyError(
            f"{PII_KEY_NAME} is only {len(key)} characters; use at least {MIN_PII_KEY_LENGTH}.")
    return key


def load_config(path=DEFAULT_CONFIG):
    with open(path, "rb") as file:
        return tomllib.load(file)


def load_settings(data_dir=None, config_path=DEFAULT_CONFIG, env_file=DEFAULT_ENV_FILE):
    return Settings(data_dir=Path(data_dir) if data_dir else REPO_ROOT / "data",
                    pii_key=read_pii_key(env_file),
                    config=load_config(config_path))


def rule_params(config):
    """Every rule and threshold value, flattened so SQL can use them as $name."""
    return {**config["rules"], **config["thresholds"]}
