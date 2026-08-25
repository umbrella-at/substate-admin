"""The settings, and the ways a host can be wrong about them.

Every test here is about a failure that would otherwise be silent. A missing JWT_SECRET must stop
the process rather than let it sign with a default; `JWT_SECRET=` in an EnvironmentFile sets the
variable to the empty string, which is "present" as far as the environment is concerned; a
DATABASE_URL naming the wrong driver must fail by name rather than deep inside engine
construction; and a settings object that ever reaches a log line must not carry three secrets in
its repr.
"""

from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from pydantic import ValidationError

from app.config import Settings, _release_file_commit, get_settings

_REQUIRED: Final = ("DATABASE_URL", "JWT_SECRET", "IP_HASH_PEPPER")
_URL: Final = "postgresql+psycopg://someone:hunter2@127.0.0.1:5432/substate"


def settings(**overrides: Any) -> Settings:
    """Build settings from explicit values, ignoring both the environment and any local .env.

    A developer's own .env would otherwise decide what these tests prove.
    """
    values: dict[str, Any] = {
        "database_url": _URL,
        "jwt_secret": "a-secret",
        "ip_hash_pepper": "a-pepper",
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


@pytest.fixture(autouse=True)
def _forget_the_release_file() -> Iterator[None]:
    """The commit is read from disk once per process and cached. Two tests need two answers."""
    _release_file_commit.cache_clear()
    yield
    _release_file_commit.cache_clear()


@pytest.fixture(autouse=True)
def _bare_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Build every Settings below from explicit values and nothing else.

    Environment variables outrank the arguments passed to the constructor, so without this the
    suite's own environment decides half of what this module proves — and the RELEASE-file test
    would pass because APP_COMMIT happens to hold the same seven characters the file does.
    """
    for name in (*_REQUIRED, "APP_ENV", "COOKIE_SECURE", "APP_COMMIT"):
        monkeypatch.delenv(name, raising=False)


def test_the_process_refuses_to_start_without_its_three_required_values() -> None:
    """A host that is missing one of these must fail its smoke check loudly instead of serving
    with a guessable signing key."""
    with pytest.raises(ValidationError) as refusal:
        Settings(_env_file=None)

    missing = {str(error["loc"][0]) for error in refusal.value.errors()}
    assert missing == {name.lower() for name in _REQUIRED}


@pytest.mark.parametrize("field", ["jwt_secret", "ip_hash_pepper", "database_url"])
def test_an_empty_secret_is_not_a_secret(field: str) -> None:
    """`JWT_SECRET=` in an EnvironmentFile is a variable that exists and is worth nothing."""
    with pytest.raises(ValidationError):
        settings(**{field: ""})


@pytest.mark.parametrize(
    "url",
    [
        # psycopg2, which is not installed and is not async.
        "postgresql://someone@127.0.0.1/substate",
        "postgresql+asyncpg://someone@127.0.0.1/substate",
        "sqlite+aiosqlite:///./substate.db",
    ],
)
def test_a_url_naming_another_driver_fails_by_name(url: str) -> None:
    """Otherwise it fails deep inside engine construction, with a message about DBAPIs."""
    with pytest.raises(ValidationError, match="postgresql\\+psycopg://"):
        settings(database_url=url)


def test_the_secrets_do_not_appear_in_the_repr() -> None:
    """A settings object handed to a log line, a traceback or a debugger prints three masks."""
    printed = repr(settings())

    assert "hunter2" not in printed
    assert "a-secret" not in printed
    assert "a-pepper" not in printed
    assert printed.count("**********") == 3


def test_the_secrets_are_readable_by_the_code_that_needs_them() -> None:
    assert settings().jwt_secret.get_secret_value() == "a-secret"


@pytest.mark.parametrize(
    ("app_env", "published"),
    [("production", False), ("development", True), ("test", True)],
)
def test_the_docs_are_published_everywhere_but_production(app_env: str, published: bool) -> None:
    assert settings(app_env=app_env).docs_enabled is published


def test_an_unset_environment_is_production() -> None:
    """An unset APP_ENV must never be the thing that decides to publish /api/docs."""
    assert settings().app_env == "production"


def test_the_cookie_is_secure_unless_a_local_env_says_otherwise() -> None:
    """Safari refuses a Secure cookie over http://localhost, so a hardcoded True breaks local
    login with no error in any console — and a default of False would ship one."""
    assert settings().cookie_secure is True
    assert settings(cookie_secure=False).cookie_secure is False


def test_the_commit_is_the_variable_when_there_is_one() -> None:
    assert settings(app_commit="deadbee").commit == "deadbee"


def test_the_commit_is_the_release_file_the_deploy_wrote(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """This is why CI never has to write the server's EnvironmentFile to report a release."""
    (tmp_path / "RELEASE").write_text("abc1234\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert settings().commit == "abc1234"


def test_the_commit_is_unknown_when_there_is_nothing_to_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    assert settings().commit == "unknown"


def test_the_accessor_refuses_a_host_that_is_missing_them() -> None:
    """`get_settings()` is what `app.main` calls at import, so this is the failure a misconfigured
    host meets: loudly, before the socket is bound."""
    get_settings.cache_clear()
    try:
        with pytest.raises(ValidationError):
            get_settings()
    finally:
        # Emptied rather than left holding a Settings built from a stripped environment.
        get_settings.cache_clear()
