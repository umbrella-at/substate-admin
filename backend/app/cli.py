"""The operator's command line: `substate-admin`.

Three subcommands, none of which needs a running web server and none of which is ever called from
application startup. `sync-permissions` runs on every deploy, immediately after
`alembic upgrade head`: at startup it would race every other worker restarting beside it, and a
failure there is a service that will not boot rather than a deploy step that stopped. `create-user`
is run by hand, once, the first time a host needs an account. `prune-tokens` runs on a timer, and
is the only thing that ever deletes a refresh token: rotation and logout mark rows, they never
remove them, so without a reaper the table only grows.

All three report to a person, not to the journal: results go to stdout as sentences and refusals
go to stderr with a non-zero exit, so `set -e` in the deploy script — and a systemd timer's
failure state — stops on them.
"""

import argparse
import asyncio
import getpass
import logging
import sys
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from pydantic import ValidationError
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import dispose_engine, get_sessionmaker, utc_now
from app.logging import configure_logging
from app.models import Permission, Role, RolePermission, User, normalize_email
from app.permissions import PERMISSION_CODES, PERMISSIONS, ROLE_CODES, SYSTEM_ROLES, SystemRole
from app.security.passwords import PasswordPolicyError, hash_password, validate_password
from app.security.refresh import PRUNE_RETENTION, prune_expired

EXIT_OK: Final = 0
EXIT_FAILURE: Final = 1

# The shell's convention for "killed by SIGINT". Ctrl-C at a password prompt is an ordinary way to
# leave this command, and it should not look like a crash.
EXIT_INTERRUPTED: Final = 130

# The ceiling `app.schemas.LoginRequest` puts on the field. A longer address would create an
# account the login endpoint can never accept a request for: unusable, and nothing reports it.
MAX_EMAIL_LENGTH: Final = 320


class CommandError(Exception):
    """A refusal the operator reads as one line. The message is the whole error report."""


@dataclass(frozen=True, slots=True)
class CreatedRole:
    """What `create_role` did."""

    id: uuid.UUID
    code: str
    name: str
    permissions: list[str]

    # False when the role already existed and only its grants were replaced.
    created: bool


@dataclass(frozen=True, slots=True)
class CreatedUser:
    """What `create_user` did."""

    id: uuid.UUID
    email: str
    role_code: str

    # False when the account already existed and only its password was replaced.
    created: bool
    is_active: bool


@dataclass(frozen=True, slots=True)
class RoleSync:
    """What one system role needed to bring it back in line with the catalogue."""

    code: str
    created: bool
    renamed: bool

    # A row that carried this code without `is_system`. It is a system role by definition of its
    # code, and the flag is what forbids deleting it.
    adopted: bool

    granted: tuple[str, ...]
    revoked: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return bool(self.created or self.renamed or self.adopted or self.granted or self.revoked)


@dataclass(frozen=True, slots=True)
class SyncReport:
    """Everything one `sync-permissions` run altered."""

    added: tuple[str, ...]
    updated: tuple[str, ...]
    removed: tuple[str, ...]
    roles: tuple[RoleSync, ...]

    @property
    def changed(self) -> bool:
        return bool(self.added or self.updated or self.removed) or any(
            role.changed for role in self.roles
        )


def normalized_email(raw: str) -> str:
    """Fold a command-line address to the stored form, refusing what cannot be one.

    This is the only path that writes `users.email`, and there is no screen anywhere that can
    correct a typo afterwards — a misspelt address is an account that silently never logs in.
    """
    email = normalize_email(raw)
    local, at, domain = email.partition("@")
    if not at or not local or not domain or "@" in domain or any(c.isspace() for c in email):
        raise CommandError(f"{raw!r} is not an email address.")
    if len(email) > MAX_EMAIL_LENGTH:
        raise CommandError(f"An email address must be at most {MAX_EMAIL_LENGTH} characters.")
    return email


def read_password() -> str:
    """Read the password from stdin, without echoing it anywhere.

    On a terminal this prompts twice and compares, because a mistyped password on this path is an
    account that cannot be recovered without running the command again. When stdin is a pipe it
    reads one line and asks nothing — that is the path CI takes, and a prompt written to a
    non-interactive stream is a build that hangs until it times out.
    """
    if sys.stdin.isatty():
        first = getpass.getpass("Password: ")
        if first != getpass.getpass("Repeat password: "):
            raise CommandError("The two passwords do not match.")
        return first

    line = sys.stdin.readline()
    if not line:
        raise CommandError("No password on stdin.")
    # Exactly one line ending, and nothing else: trailing spaces belong to the password, and
    # stripping them here would store a secret the operator cannot type again.
    return line.removesuffix("\n").removesuffix("\r")


async def create_user(
    session: AsyncSession,
    *,
    email: str,
    password: str,
    role_code: str,
    set_password: bool = False,
) -> CreatedUser:
    """Create an account, or replace the password of one that exists.

    The policy is applied here rather than by the caller, so that every path into this table
    judges a password by one rule and hashes exactly the string that was judged.
    """
    folded = validate_password(password, email=email)

    role = (
        (await session.execute(select(Role).where(Role.code == role_code, Role.world_id.is_(None))))
        .scalars()
        .first()
    )
    if role is None:
        raise CommandError(_unknown_role_message(role_code, await _known_role_codes(session)))

    existing = (
        (await session.execute(select(User).where(User.email == email, User.world_id.is_(None))))
        .scalars()
        .first()
    )
    if existing is not None:
        if not set_password:
            raise CommandError(
                f"{email} already exists. Pass --set-password to replace its password."
            )
        if existing.role.code != role_code:
            # The flag says password, so it changes a password. Refusing rather than quietly
            # re-roling the account means a mistyped --role cannot promote somebody.
            raise CommandError(
                f"{email} has the role {existing.role.code!r}, not {role_code!r}; "
                "this command does not change roles."
            )
        existing.password_hash = hash_password(folded)
        await session.commit()
        return CreatedUser(
            id=existing.id,
            email=email,
            role_code=role_code,
            created=False,
            is_active=existing.is_active,
        )

    user = User(email=email, password_hash=hash_password(folded), role_id=role.id)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError as exc:
        # The unique index, not the SELECT above: two operators running this at once, or a row
        # written between the two statements. The generic database message would say nothing.
        await session.rollback()
        raise CommandError(f"{email} already exists.") from exc
    return CreatedUser(
        id=user.id, email=email, role_code=role_code, created=True, is_active=user.is_active
    )


async def create_role(
    session: AsyncSession, *, code: str, name: str, permissions: Sequence[str]
) -> CreatedRole:
    """Create a role of the panel's own, or replace what an existing custom one grants.

    A deploy has only the four system roles, and the first custom one has to exist before anybody
    can be put on it — the same reason `create-user` exists. A system role is refused here for the
    reason the API refuses it: the next deploy would restore it.
    """
    if code in ROLE_CODES:
        raise CommandError(
            f"{code!r} is a role this application defines and restores on every deploy. "
            "Choose a code of your own."
        )
    unknown = sorted(set(permissions) - set(PERMISSION_CODES))
    if unknown:
        raise CommandError(
            f"no such permission: {', '.join(unknown)}. "
            f"The catalogue holds: {', '.join(PERMISSION_CODES)}."
        )

    role = (
        (await session.execute(select(Role).where(Role.code == code, Role.world_id.is_(None))))
        .scalars()
        .first()
    )
    created = role is None
    if role is None:
        role = Role(code=code, name=name, is_system=False)
        session.add(role)
        await session.flush()
    else:
        role.name = name
        await session.execute(delete(RolePermission).where(RolePermission.role_id == role.id))

    for permission in sorted(set(permissions)):
        session.add(RolePermission(role_id=role.id, permission_code=permission))
    await session.commit()
    return CreatedRole(
        id=role.id, code=code, name=name, created=created, permissions=sorted(set(permissions))
    )


async def sync_permissions(session: AsyncSession) -> SyncReport:
    """Force the permission table and the four system roles to match the catalogue.

    Idempotent by construction: it reads what is there, writes only the difference, and reports
    it. Custom roles are never read and never written — only the codes in `SYSTEM_ROLES` are
    touched, so a role somebody built by hand keeps its grants across every deploy.

    One transaction for the whole run. A half-synced role grants some of what it should and is
    harder to notice than one that was never synced at all.
    """
    added, updated, removed = await _sync_catalogue(session)

    # The grants below reference permission codes as a foreign key, so the rows have to exist
    # before they are granted.
    await session.flush()

    roles = tuple([await _sync_role(session, spec) for spec in SYSTEM_ROLES.values()])
    await session.commit()

    # Nothing signals the running service: it re-reads a role's permissions when its in-process
    # cache expires, thirty seconds after this commit at the latest.
    return SyncReport(added=added, updated=updated, removed=removed, roles=roles)


async def _sync_catalogue(
    session: AsyncSession,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Bring `permissions` to exactly the codes the catalogue declares."""
    stored = {row.code: row for row in (await session.execute(select(Permission))).scalars()}
    added: list[str] = []
    updated: list[str] = []
    removed: list[str] = []

    for code, description in PERMISSIONS.items():
        row = stored.get(code)
        if row is None:
            session.add(Permission(code=code, description=description))
            added.append(code)
        elif row.description != description:
            row.description = description
            updated.append(code)

    for stored_code, stored_row in stored.items():
        if stored_code not in PERMISSIONS:
            # A code the application no longer knows cannot be asked for by any route, so leaving
            # it would leave grants that grant nothing. The FK cascade removes those grants with
            # it, including a custom role's — the alternative is a dangling reference.
            await session.delete(stored_row)
            removed.append(stored_code)

    return tuple(sorted(added)), tuple(sorted(updated)), tuple(sorted(removed))


async def _sync_role(session: AsyncSession, spec: SystemRole) -> RoleSync:
    """Bring one system role, and only its own grants, to what the catalogue says.

    `world_id IS NULL` is the role of this installation. A sandbox holds copies of all four under
    the same codes, and without the predicate a deploy would force-sync whichever row came back
    first — reporting success while the real `admin` kept whatever it had.
    """
    role = (
        (await session.execute(select(Role).where(Role.code == spec.code, Role.world_id.is_(None))))
        .scalars()
        .first()
    )
    created = role is None
    renamed = False
    adopted = False

    if role is None:
        role = Role(code=spec.code, name=spec.name, is_system=True)
        session.add(role)
        # The generated id is needed as a foreign key by the grants below.
        await session.flush()
    else:
        if role.name != spec.name:
            role.name = spec.name
            renamed = True
        if not role.is_system:
            role.is_system = True
            adopted = True

    held = set(
        (
            await session.execute(
                select(RolePermission.permission_code).where(RolePermission.role_id == role.id)
            )
        ).scalars()
    )
    wanted = set(spec.permissions)
    granted = tuple(sorted(wanted - held))
    revoked = tuple(sorted(held - wanted))

    for code in granted:
        session.add(RolePermission(role_id=role.id, permission_code=code))
    if revoked:
        await session.execute(
            delete(RolePermission).where(
                RolePermission.role_id == role.id,
                RolePermission.permission_code.in_(revoked),
            )
        )

    return RoleSync(
        code=spec.code,
        created=created,
        renamed=renamed,
        adopted=adopted,
        granted=granted,
        revoked=revoked,
    )


def render_created_role(result: CreatedRole) -> list[str]:
    verb = "Created" if result.created else "Replaced what"
    granted = ", ".join(result.permissions) if result.permissions else "nothing"
    return [f"{verb} the role {result.code} ({result.id}) grants: {granted}."]


async def prune_tokens(session: AsyncSession) -> int:
    """Delete the refresh-token rows that are past their retention. Returns how many went.

    Safe at any hour and safe run twice: a row is only taken once it has been unexchangeable for
    a week, so nothing anybody is still holding is swept away, and a second run the same night
    finds nothing left. The clock this reads is the real one — a maintenance job that could be
    told what time it is would be a maintenance job that could be told to delete more.
    """
    return await prune_expired(session, now=utc_now())


def render_pruned(deleted: int) -> list[str]:
    """The report a person, or the timer's journal entry, reads after `prune-tokens`."""
    if deleted == 0:
        return ["No expired refresh tokens to remove."]
    tokens = "token" if deleted == 1 else "tokens"
    return [f"Removed {deleted} expired refresh {tokens}."]


async def _known_role_codes(session: AsyncSession) -> tuple[str, ...]:
    result = await session.execute(
        select(Role.code).where(Role.world_id.is_(None)).order_by(Role.code)
    )
    return tuple(result.scalars())


def _unknown_role_message(role_code: str, known: Sequence[str]) -> str:
    if not known:
        return (
            f"No role {role_code!r} exists — the roles table is empty. "
            "Run `substate-admin sync-permissions` first."
        )
    return f"No role {role_code!r} exists. Roles: {', '.join(known)}."


def render_created(result: CreatedUser) -> list[str]:
    """The report a person reads after `create-user`."""
    if result.created:
        lines = [f"Created {result.email} ({result.id}) with the role {result.role_code}."]
    else:
        lines = [f"Replaced the password of {result.email} ({result.id})."]
    if not result.is_active:
        # A password reset on a disabled account looks like it worked and then fails at login
        # with the same message as a wrong password. Say so here, where it is still visible.
        lines.append("This account is not active, so it cannot sign in.")
    return lines


def render_sync(report: SyncReport) -> list[str]:
    """The report a person reads after `sync-permissions`, and the deploy log keeps."""
    if not report.changed:
        return [
            f"Already in sync: {len(PERMISSIONS)} permissions, {len(SYSTEM_ROLES)} system roles."
        ]

    lines: list[str] = []
    if report.added:
        lines.append(f"Permissions added: {', '.join(report.added)}.")
    if report.updated:
        lines.append(f"Descriptions updated: {', '.join(report.updated)}.")
    if report.removed:
        lines.append(f"Permissions removed: {', '.join(report.removed)}.")

    for role in report.roles:
        if not role.changed:
            continue
        parts: list[str] = []
        if role.created:
            parts.append("created")
        if role.renamed:
            parts.append("renamed")
        if role.adopted:
            parts.append("marked as a system role")
        if role.granted:
            parts.append(f"granted {', '.join(role.granted)}")
        if role.revoked:
            parts.append(f"revoked {', '.join(role.revoked)}")
        lines.append(f"Role {role.code}: {'; '.join(parts)}.")

    lines.append(f"Synchronised {len(PERMISSIONS)} permissions and {len(SYSTEM_ROLES)} roles.")
    return lines


def _require_settings() -> None:
    """Fail on a half-written environment before anything else is attempted.

    The CLI loads the same settings as the service, secrets it will not use included. That is the
    point: the first command the deploy runs is this one, so a host whose EnvironmentFile is
    missing JWT_SECRET stops here instead of passing the migration and failing the smoke check.
    """
    try:
        get_settings()
    except ValidationError as exc:
        # The variable name and pydantic's reason, never the value: two of the three fields this
        # reports on are secrets. Its own messages carry no input, but the prefix a field
        # validator's message is given ("Value error, ") is noise to whoever is reading.
        problems = sorted(
            f"{str(error['loc'][0]).upper()}: {error['msg'].removeprefix('Value error, ')}"
            for error in exc.errors()
            if error["loc"]
        )
        raise CommandError(f"Configuration — {'; '.join(problems)}.") from exc


def _run(work: Callable[[AsyncSession], Awaitable[list[str]]]) -> list[str]:
    """Open one session, run the command in it, and translate what the database says."""

    async def main_task() -> list[str]:
        try:
            async with get_sessionmaker()() as session:
                return await work(session)
        finally:
            # The engine holds a live pool. Exiting without disposing it leaves psycopg to close
            # connections from a garbage collector that is already shutting the loop down, which
            # it complains about on stderr after the command has printed its result.
            await dispose_engine()

    try:
        return asyncio.run(main_task())
    except (SQLAlchemyError, OSError) as exc:
        # The exception type and nothing more: a psycopg connection error quotes the DSN it tried,
        # and the DSN carries the password.
        raise CommandError(
            f"The database is not answering ({type(exc).__name__}). "
            "Check DATABASE_URL and that Postgres is running."
        ) from exc


def _create_user_command(args: argparse.Namespace) -> list[str]:
    email = normalized_email(args.email)
    role_code: str = args.role
    set_password: bool = args.set_password
    password = read_password()

    async def work(session: AsyncSession) -> list[str]:
        result = await create_user(
            session,
            email=email,
            password=password,
            role_code=role_code,
            set_password=set_password,
        )
        return render_created(result)

    return _run(work)


def _create_role_command(args: argparse.Namespace) -> list[str]:
    code: str = args.code
    name: str = args.name
    permissions: list[str] = list(args.grant or ())

    async def work(session: AsyncSession) -> list[str]:
        return render_created_role(
            await create_role(session, code=code, name=name, permissions=permissions)
        )

    return _run(work)


def _sync_permissions_command(_: argparse.Namespace) -> list[str]:
    async def work(session: AsyncSession) -> list[str]:
        return render_sync(await sync_permissions(session))

    return _run(work)


def _prune_tokens_command(_: argparse.Namespace) -> list[str]:
    async def work(session: AsyncSession) -> list[str]:
        return render_pruned(await prune_tokens(session))

    return _run(work)


COMMANDS: Final[Mapping[str, Callable[[argparse.Namespace], list[str]]]] = {
    "create-user": _create_user_command,
    "create-role": _create_role_command,
    "sync-permissions": _sync_permissions_command,
    "prune-tokens": _prune_tokens_command,
}


def build_parser() -> argparse.ArgumentParser:
    """The argument parser, named for the console script rather than for however it was invoked."""
    parser = argparse.ArgumentParser(
        prog="substate-admin", description="Administrative commands for the substate admin panel."
    )
    subparsers = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    create = subparsers.add_parser(
        "create-user",
        help="Create an account, reading its password from stdin.",
        description=(
            "Create an account. The password is read from stdin: prompted twice on a terminal, "
            "read as one line when piped."
        ),
    )
    create.add_argument("--email", required=True, help="The account's email address.")
    create.add_argument(
        "--role",
        required=True,
        help=f"The role's code. System roles: {', '.join(ROLE_CODES)}.",
    )
    create.add_argument(
        "--set-password",
        action="store_true",
        help="Replace the password of an account that already exists.",
    )

    role = subparsers.add_parser(
        "create-role",
        help="Create a role of your own, or replace what one grants.",
        description=(
            "Create a role the panel's own operators can be put on, or replace the grants of one "
            "that exists. A deploy ships only the four system roles, and those are refused here: "
            "the next deploy would restore them. Idempotent on the code."
        ),
    )
    role.add_argument("--code", required=True, help="The role's code, as people will refer to it.")
    role.add_argument("--name", required=True, help="The role's name, as a screen shows it.")
    role.add_argument(
        "--grant",
        action="append",
        metavar="PERMISSION",
        help="A permission this role grants. Repeat for each; omit for a role that grants nothing.",
    )

    subparsers.add_parser(
        "prune-tokens",
        help="Delete refresh tokens nobody can exchange any more.",
        description=(
            "Delete every row in refresh_tokens that has been unexchangeable for more than "
            f"{PRUNE_RETENTION.days} days, and report how many went. Nothing else in the "
            "application deletes these rows: rotation and logout mark them, so this is the only "
            "thing standing between the table and unbounded growth. The delay before a row goes "
            "is retention rather than caution — an expired row is the evidence behind a reuse "
            "alarm, and it is worth keeping for as long as somebody might still be reading that "
            "alarm. Running it removes nothing any client is holding, and running it twice is "
            "harmless. Schedule it once a day, from cron or a systemd timer, rather than calling "
            "it from the service: it is a maintenance job, and a service that swept its own "
            "tables would sweep them once per worker."
        ),
    )

    subparsers.add_parser(
        "sync-permissions",
        help="Force the permission table and the system roles to match the catalogue.",
        description=(
            "Force the permission table and the four system roles to match the catalogue "
            "compiled into this release. Idempotent, and custom roles are left alone. Run it "
            "after `alembic upgrade head`."
        ),
    )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the `substate-admin` console script."""
    args = build_parser().parse_args(argv)

    # Warnings only. This command talks to a person in sentences; logging is configured so that
    # anything a library has to say arrives as the same JSON the service writes, not as a line of
    # its own invention in the middle of a report.
    configure_logging(level=logging.WARNING)

    try:
        # Before the password prompt and before the first connection: a host with a half-written
        # environment should be told that, not made to type a password first.
        _require_settings()
        lines = COMMANDS[args.command](args)
    except (CommandError, PasswordPolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_FAILURE
    except KeyboardInterrupt:
        return EXIT_INTERRUPTED

    for line in lines:
        print(line)
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
