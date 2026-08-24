"""Process configuration, read once from the environment.

In production the values arrive from /etc/substate-admin/api.env through the systemd unit's
EnvironmentFile. Locally they come from a .env beside this package, which is never committed.
"""

from functools import lru_cache
from pathlib import Path
from typing import Final, Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

AppEnv = Literal["production", "development", "test"]

# The deploy writes this file into the release directory, which is also the service's working
# directory. Reading it is what lets CI report the running commit without ever touching the
# server's EnvironmentFile.
_RELEASE_FILE: Final = "RELEASE"
_UNKNOWN_COMMIT: Final = "unknown"

# psycopg 3 in async mode. `postgresql://` silently selects psycopg2 and `postgresql+asyncpg://`
# selects a driver that is not installed; both fail deep inside engine construction with a
# message about DBAPIs. Rejecting the URL here names the actual problem.
_REQUIRED_DRIVER: Final = "postgresql+psycopg://"


@lru_cache(maxsize=1)
def _release_file_commit() -> str:
    """Read the release marker the deploy leaves in the working directory."""
    try:
        commit = Path(_RELEASE_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return _UNKNOWN_COMMIT
    return commit or _UNKNOWN_COMMIT


class Settings(BaseSettings):
    """Everything this process needs to know that is not in the code."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        # api.env is also read by the deploy shell and may grow keys this process does not care
        # about; an unknown variable must not stop the service from starting.
        extra="ignore",
    )

    # No defaults and no fallbacks. A host that is missing one of these must fail its smoke
    # check loudly instead of serving with a guessable signing key or a hash pepper of "".
    # min_length is not cosmetic either: `JWT_SECRET=` in an EnvironmentFile sets the variable
    # to the empty string, which is "present" as far as the environment is concerned.
    database_url: SecretStr = Field(min_length=1)
    jwt_secret: SecretStr = Field(min_length=1)
    ip_hash_pepper: SecretStr = Field(min_length=1)

    # Production is the default because an unset APP_ENV must never be the thing that decides to
    # publish /api/docs.
    app_env: AppEnv = "production"

    # Safari refuses a Secure cookie over http://localhost, so a hardcoded True breaks local
    # login with no error in any console. Only a local .env sets this false.
    cookie_secure: bool = True

    app_commit: str | None = None

    @field_validator("database_url")
    @classmethod
    def _require_psycopg_driver(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().startswith(_REQUIRED_DRIVER):
            raise ValueError(f"DATABASE_URL must start with {_REQUIRED_DRIVER}")
        return value

    @property
    def docs_enabled(self) -> bool:
        """Whether /api/docs and /api/openapi.json are mounted."""
        return self.app_env != "production"

    @property
    def commit(self) -> str:
        """The commit this release was built from, as reported by GET /api/health."""
        return self.app_commit or _release_file_commit()


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """The settings for this process, built on first use.

    Lazy for the same reason the engine is: importing a module must not require a configured
    machine. Tests that need a different environment call `get_settings.cache_clear()`.
    """
    # The three required values come from the environment, not from this call. The __init__ that
    # dataclass_transform synthesises for every pydantic model has no way to know that, and asks
    # for them as arguments.
    return Settings()  # type: ignore[call-arg]
