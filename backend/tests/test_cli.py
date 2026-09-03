"""`substate-admin`, the commands the deploy, the timer and the first operator run.

`sync-permissions` runs on every deploy, so what matters about it is that running it twice is
indistinguishable from running it once, that it repairs a role somebody edited by hand, and that
it never touches a role it did not create. `create-user` writes the only rows that can ever sign
in, and there is no screen anywhere to correct what it gets wrong — so its refusals are tested as
carefully as its successes. `prune-tokens` is the only thing in the project that deletes a
refresh token, so what is tested is exactly which rows it takes: a job that swept a live session
away would log people out at whatever hour the timer fires.

The command functions are exercised against the test session; the argument parsing and the two
refusals that happen before any connection is opened are exercised through `main` itself.
"""

import asyncio
import getpass
import io
import os
import sys
import uuid
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import create_engine, delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.pool import NullPool

from app.cli import (
    EXIT_FAILURE,
    EXIT_OK,
    CommandError,
    CreatedUser,
    RoleSync,
    SyncReport,
    build_parser,
    create_role,
    create_user,
    main,
    normalized_email,
    prune_tokens,
    read_password,
    render_created,
    render_pruned,
    render_sync,
    sync_permissions,
)
from app.config import get_settings
from app.db import dispose_engine, utc_now
from app.models import Permission, RefreshToken, Role, RolePermission, User
from app.permissions import PERMISSIONS, ROLE_CODES, SYSTEM_ROLES
from app.security.passwords import PasswordPolicyError, verify_password
from app.security.refresh import PRUNE_RETENTION, RevocationReason
from support import create_account, role_id_for

_PASSWORD: Final = "a-command-line-password"

# A port nothing listens on, with a password in the DSN so that a leak would be visible.
_UNREACHABLE: Final = "postgresql+psycopg://someone:hunter2@127.0.0.1:1/nowhere"


@pytest.fixture
def unreachable_database() -> Iterator[None]:
    """Point the process at a database that is not there, and leave nothing behind."""
    original = os.environ["DATABASE_URL"]
    os.environ["DATABASE_URL"] = _UNREACHABLE
    get_settings.cache_clear()
    asyncio.run(dispose_engine())
    try:
        yield
    finally:
        os.environ["DATABASE_URL"] = original
        get_settings.cache_clear()
        asyncio.run(dispose_engine())


async def test_sync_permissions_run_twice_changes_nothing_the_second_time(
    session: AsyncSession,
) -> None:
    """The session-scoped seed already ran it, so this is the second run and the third."""
    assert (await sync_permissions(session)).changed is False
    assert (await sync_permissions(session)).changed is False


async def test_the_catalogue_matches_what_the_application_declares(
    session: AsyncSession,
) -> None:
    rows = (await session.execute(select(Permission.code, Permission.description))).tuples()

    assert {code: description for code, description in rows} == dict(PERMISSIONS)


async def test_every_system_role_is_marked_as_one(session: AsyncSession) -> None:
    """`is_system` is what forbids deleting a role out from under its users."""
    rows = (
        await session.execute(select(Role.code, Role.name, Role.is_system).order_by(Role.code))
    ).tuples()

    assert {code: (name, is_system) for code, name, is_system in rows} == {
        spec.code: (spec.name, True) for spec in SYSTEM_ROLES.values()
    }


async def test_sync_permissions_repairs_a_role_somebody_edited(session: AsyncSession) -> None:
    admin = await role_id_for(session, "admin")
    await session.execute(
        delete(RolePermission).where(
            RolePermission.role_id == admin, RolePermission.permission_code == "users.write"
        )
    )
    await session.execute(
        update(Role).where(Role.id == admin).values(name="Whatever", is_system=False)
    )
    await session.commit()

    report = await sync_permissions(session)

    repaired = next(role for role in report.roles if role.code == "admin")
    assert repaired.granted == ("users.write",)
    assert repaired.renamed is True
    assert repaired.adopted is True
    assert repaired.revoked == ()
    assert (await sync_permissions(session)).changed is False


async def test_sync_permissions_revokes_a_grant_the_catalogue_does_not_give(
    session: AsyncSession,
) -> None:
    viewer = await role_id_for(session, "viewer")
    session.add(RolePermission(role_id=viewer, permission_code="users.write"))
    await session.commit()

    report = await sync_permissions(session)

    repaired = next(role for role in report.roles if role.code == "viewer")
    assert repaired.revoked == ("users.write",)


async def test_sync_permissions_never_touches_a_role_it_did_not_create(
    session: AsyncSession,
) -> None:
    """A role somebody built by hand keeps its grants across every deploy."""
    custom = Role(code="auditor", name="Auditor")
    session.add(custom)
    await session.flush()
    session.add(RolePermission(role_id=custom.id, permission_code="audit.read"))
    await session.commit()

    report = await sync_permissions(session)

    assert [role.code for role in report.roles] == list(ROLE_CODES)
    held = (
        (
            await session.execute(
                select(RolePermission.permission_code).where(RolePermission.role_id == custom.id)
            )
        )
        .scalars()
        .all()
    )
    assert list(held) == ["audit.read"]
    assert (
        await session.execute(select(Role.is_system).where(Role.id == custom.id))
    ).scalar_one() is False


async def test_a_code_the_catalogue_dropped_goes_and_takes_its_grants_with_it(
    session: AsyncSession,
) -> None:
    """A code no route can ask for leaves grants that grant nothing, and a dangling reference is
    worse than the removal."""
    session.add(Permission(code="legacy.read", description="From a release nobody runs."))
    custom = Role(code="auditor", name="Auditor")
    session.add(custom)
    await session.flush()
    session.add(RolePermission(role_id=custom.id, permission_code="legacy.read"))
    await session.commit()

    report = await sync_permissions(session)

    assert report.removed == ("legacy.read",)
    remaining = (
        await session.execute(
            select(func.count())
            .select_from(RolePermission)
            .where(RolePermission.role_id == custom.id)
        )
    ).scalar_one()
    assert remaining == 0


async def test_create_user_writes_an_account_that_can_sign_in(session: AsyncSession) -> None:
    result = await create_user(
        session, email="operator@example.com", password=_PASSWORD, role_code="support"
    )

    assert result == CreatedUser(
        id=result.id,
        email="operator@example.com",
        role_code="support",
        created=True,
        is_active=True,
    )
    stored = (
        await session.execute(select(User.password_hash).where(User.id == result.id))
    ).scalar_one()
    assert verify_password(_PASSWORD, stored).ok


async def test_create_user_applies_the_one_password_policy(session: AsyncSession) -> None:
    """The same validator login's future write endpoints will use. Two implementations of "is
    this acceptable" would eventually disagree, quietly."""
    with pytest.raises(PasswordPolicyError):
        await create_user(
            session, email="short@example.com", password="tooshort", role_code="admin"
        )

    assert await _count_users(session, "short@example.com") == 0


async def test_create_user_refuses_an_address_that_already_exists(
    session: AsyncSession,
) -> None:
    await create_user(session, email="taken@example.com", password=_PASSWORD, role_code="admin")

    with pytest.raises(CommandError, match="--set-password"):
        await create_user(session, email="taken@example.com", password=_PASSWORD, role_code="admin")


async def test_create_user_replaces_a_password_when_told_to(session: AsyncSession) -> None:
    created = await create_user(
        session, email="reset@example.com", password=_PASSWORD, role_code="admin"
    )

    result = await create_user(
        session,
        email="reset@example.com",
        password="a-completely-different-one",
        role_code="admin",
        set_password=True,
    )

    assert result.created is False
    assert result.id == created.id
    stored = (
        await session.execute(select(User.password_hash).where(User.id == created.id))
    ).scalar_one()
    assert verify_password("a-completely-different-one", stored).ok
    assert not verify_password(_PASSWORD, stored).ok


async def test_setting_a_password_does_not_change_a_role(session: AsyncSession) -> None:
    """The flag says password, so a mistyped --role cannot promote somebody."""
    await create_user(session, email="viewer@example.com", password=_PASSWORD, role_code="viewer")

    with pytest.raises(CommandError, match="does not change roles"):
        await create_user(
            session,
            email="viewer@example.com",
            password=_PASSWORD,
            role_code="admin",
            set_password=True,
        )


async def test_create_user_refuses_a_role_nobody_defined(session: AsyncSession) -> None:
    with pytest.raises(CommandError, match="Roles: admin"):
        await create_user(
            session, email="nobody@example.com", password=_PASSWORD, role_code="wizard"
        )

    assert await _count_users(session, "nobody@example.com") == 0


async def test_the_command_stores_the_address_in_the_form_the_column_holds(
    session: AsyncSession,
) -> None:
    """`normalized_email` is what folds it, and the command applies it before this function sees
    an address. The unique index is a plain btree over text — no citext — so a row written in any
    other form is an account login can never find."""
    result = await create_user(
        session,
        email=normalized_email("Mixed.Case@Example.COM"),
        password=_PASSWORD,
        role_code="admin",
    )

    assert result.email == "mixed.case@example.com"
    stored = (await session.execute(select(User.email).where(User.id == result.id))).scalar_one()
    assert stored == "mixed.case@example.com"


@pytest.mark.parametrize(
    "raw",
    ["not-an-email", "@example.com", "someone@", "some one@example.com", "a@b@example.com", ""],
)
def test_an_address_that_cannot_be_one_is_refused(raw: str) -> None:
    """There is no screen anywhere that can correct a typo afterwards: a misspelt address is an
    account that silently never logs in."""
    with pytest.raises(CommandError):
        normalized_email(raw)


def test_an_address_longer_than_the_login_field_accepts_is_refused() -> None:
    """Otherwise this command creates an account the login endpoint can never receive a request
    for."""
    with pytest.raises(CommandError, match="at most 320"):
        normalized_email("x" * 320 + "@example.com")


def test_an_address_is_folded_the_way_the_column_stores_it() -> None:
    assert normalized_email("  Someone@Example.COM  ") == "someone@example.com"


def test_a_piped_password_is_one_line_and_nothing_is_prompted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The path CI takes. A prompt written to a non-interactive stream is a build that hangs."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("a-piped-password\n"))

    assert read_password() == "a-piped-password"


def test_a_piped_password_keeps_its_trailing_spaces(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stripping them here would store a secret the operator cannot type again."""
    monkeypatch.setattr(sys, "stdin", io.StringIO("  spaced  \r\n"))

    assert read_password() == "  spaced  "


def test_an_empty_stdin_is_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(""))

    with pytest.raises(CommandError, match="No password"):
        read_password()


def test_the_parser_names_the_console_script_rather_than_however_it_was_invoked() -> None:
    parser = build_parser()

    assert parser.prog == "substate-admin"
    parsed = parser.parse_args(["create-user", "--email", "a@b.co", "--role", "admin"])
    assert parsed.command == "create-user"
    assert parsed.set_password is False


def test_no_subcommand_is_a_usage_error() -> None:
    with pytest.raises(SystemExit) as exit_code:
        main([])

    assert exit_code.value.code == 2


def test_a_refusal_is_one_line_on_stderr_and_a_non_zero_exit(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """`set -e` in the deploy script stops on this, and a person reads the line above it."""
    code = main(["create-user", "--email", "not-an-email", "--role", "admin"])

    assert code == EXIT_FAILURE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: ")
    assert captured.err.count("\n") == 1


def test_the_report_says_what_was_done() -> None:
    created = CreatedUser(
        id=uuid.UUID(int=1),
        email="someone@example.com",
        role_code="admin",
        created=True,
        is_active=True,
    )

    assert "Created someone@example.com" in render_created(created)[0]


def test_the_report_warns_about_an_account_that_cannot_sign_in() -> None:
    """A password reset on a disabled account looks like it worked and then fails at login with
    the same message as a wrong password."""
    reset = CreatedUser(
        id=uuid.UUID(int=2),
        email="someone@example.com",
        role_code="admin",
        created=False,
        is_active=False,
    )

    lines = render_created(reset)

    assert lines[0].startswith("Replaced the password")
    assert "cannot sign in" in lines[1]


def test_an_unchanged_sync_says_so_in_one_line() -> None:
    unchanged = tuple(
        RoleSync(code=code, created=False, renamed=False, adopted=False, granted=(), revoked=())
        for code in ROLE_CODES
    )

    report = render_sync(SyncReport(added=(), updated=(), removed=(), roles=unchanged))

    assert len(report) == 1
    assert "Already in sync" in report[0]


async def _count_users(session: AsyncSession, email: str) -> int:
    return (
        await session.execute(select(func.count()).select_from(User).where(User.email == email))
    ).scalar_one()


def test_a_terminal_is_prompted_twice_and_the_two_are_compared(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mistyped password on this path is an account that cannot be recovered without running the
    command again, and there is no second chance to notice."""
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    typed = iter(["a-typed-password", "a-typed-password"])
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: next(typed))

    assert read_password() == "a-typed-password"


def test_two_different_typings_are_a_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    typed = iter(["a-typed-password", "a-typoed-password"])
    monkeypatch.setattr(getpass, "getpass", lambda _prompt: next(typed))

    with pytest.raises(CommandError, match="do not match"):
        read_password()


def test_the_report_lists_what_one_sync_altered() -> None:
    report = SyncReport(
        added=("demo.control",),
        updated=("plans.read",),
        removed=("legacy.read",),
        roles=(
            RoleSync(
                code="admin",
                created=True,
                renamed=True,
                adopted=True,
                granted=("users.write",),
                revoked=("legacy.read",),
            ),
            RoleSync(
                code="viewer",
                created=False,
                renamed=False,
                adopted=False,
                granted=(),
                revoked=(),
            ),
        ),
    )

    lines = render_sync(report)

    assert "Permissions added: demo.control." in lines
    assert "Descriptions updated: plans.read." in lines
    assert "Permissions removed: legacy.read." in lines
    admin = next(line for line in lines if line.startswith("Role admin"))
    for said in (
        "created",
        "renamed",
        "marked as a system role",
        "granted users.write",
        "revoked legacy.read",
    ):
        assert said in admin
    # A role with nothing to say is not mentioned at all.
    assert not any(line.startswith("Role viewer") for line in lines)


def test_a_database_that_does_not_answer_is_reported_without_its_password(
    capsys: pytest.CaptureFixture[str], unreachable_database: None
) -> None:
    """The first command the deploy runs. A psycopg connection error quotes the DSN it tried, and
    the DSN carries the password."""
    code = main(["sync-permissions"])

    assert code == EXIT_FAILURE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: The database is not answering")
    assert "DATABASE_URL" in captured.err
    assert "hunter2" not in captured.err


def test_a_half_written_environment_stops_before_the_password_prompt(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A host whose EnvironmentFile is missing JWT_SECRET stops here rather than passing the
    migration and failing the smoke check — and the value is never echoed, only the name."""
    monkeypatch.delenv("JWT_SECRET", raising=False)
    get_settings.cache_clear()
    try:
        code = main(["sync-permissions"])
    finally:
        get_settings.cache_clear()

    assert code == EXIT_FAILURE
    captured = capsys.readouterr()
    assert "JWT_SECRET" in captured.err
    assert captured.err.count("\n") == 1


async def test_a_description_the_catalogue_rewrote_is_brought_up_to_date(
    session: AsyncSession,
) -> None:
    """The catalogue in the code is the source of truth, including for the sentences in it."""
    await session.execute(
        update(Permission)
        .where(Permission.code == "plans.read")
        .values(description="Something an earlier release said.")
    )
    await session.commit()

    report = await sync_permissions(session)

    assert report.updated == ("plans.read",)
    stored = (
        await session.execute(select(Permission.description).where(Permission.code == "plans.read"))
    ).scalar_one()
    assert stored == PERMISSIONS["plans.read"]


async def test_a_system_role_that_is_missing_is_created_with_its_grants(
    session: AsyncSession,
) -> None:
    """The path a fresh deploy takes on an empty database."""
    demo = await role_id_for(session, "demo")
    await session.execute(delete(RolePermission).where(RolePermission.role_id == demo))
    await session.execute(delete(Role).where(Role.id == demo))
    await session.commit()

    report = await sync_permissions(session)

    created = next(role for role in report.roles if role.code == "demo")
    assert created.created is True
    assert set(created.granted) == set(SYSTEM_ROLES["demo"].permissions)
    assert (await sync_permissions(session)).changed is False


async def test_an_empty_roles_table_is_named_as_the_thing_to_fix(session: AsyncSession) -> None:
    """`create-user` before `sync-permissions` is the order somebody will try on a new host."""
    await session.execute(delete(RolePermission))
    await session.execute(delete(Role))
    await session.commit()

    with pytest.raises(CommandError, match="sync-permissions"):
        await create_user(session, email="first@example.com", password=_PASSWORD, role_code="admin")


def test_the_whole_command_creates_an_account_from_a_piped_password(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """End to end, through `main`, against the real database — the way the deploy runs it. This is
    the one test that writes outside a transaction, so it removes what it wrote.
    """
    email = f"cli-{uuid.uuid4().hex}@example.com"
    monkeypatch.setattr(sys, "stdin", io.StringIO(f"{_PASSWORD}\n"))
    try:
        code = main(["create-user", "--email", email, "--role", "support"])

        assert code == EXIT_OK
        out = capsys.readouterr().out
        assert f"Created {email}" in out
        assert "support" in out
        assert _PASSWORD not in out
    finally:
        _delete_user(email)


def _delete_user(email: str) -> None:
    """Remove one row through a connection of its own: `main` ran in a process-wide session that
    has already been disposed."""
    engine = create_engine(os.environ["DATABASE_URL"], poolclass=NullPool)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("DELETE FROM admin.users WHERE email = :email"), {"email": email}
            )
    finally:
        engine.dispose()


async def test_prune_tokens_takes_the_long_dead_rows_and_nothing_else(
    session: AsyncSession,
) -> None:
    """A live session is not evidence and a week-old alarm still is. A job that swept either away
    would be discovered by somebody being logged out at whatever hour the timer fires."""
    now = utc_now()
    account = await create_account(session, email=f"reaper-{uuid.uuid4().hex}@example.com")
    live = await _refresh_row(session, account.id, expires_at=now + timedelta(days=1))
    yesterday = await _refresh_row(session, account.id, expires_at=now - timedelta(days=1))
    await _refresh_row(session, account.id, expires_at=now - PRUNE_RETENTION - timedelta(days=1))
    await _refresh_row(
        session,
        account.id,
        expires_at=now - timedelta(days=120),
        revoked_at=now - PRUNE_RETENTION - timedelta(hours=1),
    )

    assert await prune_tokens(session) == 2

    assert await _hashes_of(session, account.id) == {live, yesterday}


async def test_prune_tokens_run_twice_removes_nothing_the_second_time(
    session: AsyncSession,
) -> None:
    """It runs every night against a table that is usually already clean, and the second run of a
    night somebody triggered by hand has to be a no-op rather than a second report."""
    now = utc_now()
    account = await create_account(session, email=f"reaper-{uuid.uuid4().hex}@example.com")
    await _refresh_row(session, account.id, expires_at=now - PRUNE_RETENTION - timedelta(days=30))

    assert await prune_tokens(session) == 1
    assert await prune_tokens(session) == 0


def test_the_prune_report_counts_what_it_took() -> None:
    assert render_pruned(0) == ["No expired refresh tokens to remove."]
    assert render_pruned(1) == ["Removed 1 expired refresh token."]
    assert render_pruned(4) == ["Removed 4 expired refresh tokens."]


def test_the_prune_help_says_how_the_command_is_meant_to_be_scheduled(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Nothing in the application calls this, so whoever reads `--help` is the person who has to
    put it on a schedule. The text has to tell them what kind."""
    with pytest.raises(SystemExit) as exit_code:
        main(["prune-tokens", "--help"])

    assert exit_code.value.code == 0
    help_text = capsys.readouterr().out
    assert "cron" in help_text
    assert "systemd timer" in help_text


def test_a_prune_that_cannot_reach_the_database_fails_loudly(
    capsys: pytest.CaptureFixture[str], unreachable_database: None
) -> None:
    """It runs unattended, so the exit code is the whole report: a timer that silently succeeded
    while the table grew would be found by disk usage, months later."""
    code = main(["prune-tokens"])

    assert code == EXIT_FAILURE
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err.startswith("error: The database is not answering")
    assert "hunter2" not in captured.err


def test_the_whole_prune_command_runs_the_way_the_timer_runs_it(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """End to end, through `main`, outside any transaction. Safe to run here despite that: the
    only rows it can take are ones no request could exchange any more."""
    code = main(["prune-tokens"])

    assert code == EXIT_OK
    assert "expired refresh token" in capsys.readouterr().out


async def _refresh_row(
    session: AsyncSession,
    user_id: uuid.UUID,
    *,
    expires_at: datetime,
    revoked_at: datetime | None = None,
) -> str:
    """One `refresh_tokens` row, written straight in and committed.

    Rotation is not what is under test here, and going through it would tie these tests to the
    thirty- and ninety-day arithmetic instead of to the one column the reaper reads.
    """
    # 64 hex characters, the shape sha256 produces, under the unique index the real hashes use.
    token_hash = uuid.uuid4().hex + uuid.uuid4().hex
    session.add(
        RefreshToken(
            user_id=user_id,
            token_hash=token_hash,
            family_id=uuid.uuid4(),
            expires_at=expires_at,
            family_expires_at=expires_at + timedelta(days=60),
            revoked_at=revoked_at,
            # The column carries a CHECK that ties the two together, and LOGOUT is the case the
            # reaper has to get right: signing out of a laptop that has been shut for a month
            # writes today's date onto a row that expired weeks ago.
            revoked_reason=None if revoked_at is None else RevocationReason.LOGOUT,
        )
    )
    await session.commit()
    return token_hash


async def _hashes_of(session: AsyncSession, user_id: uuid.UUID) -> set[str]:
    result = await session.execute(
        select(RefreshToken.token_hash).where(RefreshToken.user_id == user_id)
    )
    return set(result.scalars())


async def test_create_role_writes_a_role_of_the_panels_own(session: AsyncSession) -> None:
    """A deploy ships the four system roles, and the first custom one has to exist before anybody
    can be put on it — the same reason `create-user` exists."""
    result = await create_role(
        session, code="analysts", name="Analysts", permissions=["analytics.read", "audit.read"]
    )

    assert result.created is True
    assert result.permissions == ["analytics.read", "audit.read"]

    role = (await session.execute(select(Role).where(Role.code == "analysts"))).scalar_one()
    assert role.is_system is False
    granted = (
        (
            await session.execute(
                select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
            )
        )
        .scalars()
        .all()
    )
    assert sorted(granted) == ["analytics.read", "audit.read"]


async def test_create_role_run_twice_replaces_what_it_grants(session: AsyncSession) -> None:
    """Idempotent on the code, so provisioning can be re-run. The grants are a replacement rather
    than an addition, for the reason the API's PUT is one: the caller sends the whole set."""
    first = await create_role(session, code="analysts", name="Analysts", permissions=["audit.read"])
    again = await create_role(
        session, code="analysts", name="Auditors", permissions=["analytics.read"]
    )

    assert again.created is False
    assert again.id == first.id
    assert again.permissions == ["analytics.read"]
    role = (await session.execute(select(Role).where(Role.code == "analysts"))).scalar_one()
    assert role.name == "Auditors"


@pytest.mark.parametrize("code", ROLE_CODES)
async def test_create_role_refuses_a_role_the_deploy_would_restore(
    session: AsyncSession, code: str
) -> None:
    """The same refusal the API makes, and for the same reason: `sync-permissions` runs on every
    deploy, so an accepted edit here would be undone at the next push."""
    with pytest.raises(CommandError, match="restores on every deploy"):
        await create_role(session, code=code, name="Mine now", permissions=[])


async def test_create_role_refuses_a_permission_this_application_does_not_have(
    session: AsyncSession,
) -> None:
    """Named, so a typo is a sentence rather than a foreign key error."""
    with pytest.raises(CommandError, match=r"no such permission: users\.raed"):
        await create_role(session, code="wrong", name="Wrong", permissions=["users.raed"])

    assert (
        await session.execute(select(Role).where(Role.code == "wrong"))
    ).scalar_one_or_none() is None


async def test_create_role_grants_nothing_when_told_nothing(session: AsyncSession) -> None:
    """A role that grants nothing is an ordinary row: its holder can sign in and see the dashboard
    and nothing else, which is what the dashboard's empty state is written for."""
    result = await create_role(session, code="newcomers", name="Newcomers", permissions=[])
    assert result.permissions == []
