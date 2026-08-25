"""Alembic environment.

Synchronous, over the same psycopg 3 driver the application uses asynchronously: a migration is
one connection running DDL to completion, and there is nothing for an event loop to overlap.
"""

import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import Connection, create_engine, pool
from sqlalchemy.schema import CreateSchema

from app.config import get_settings
from app.models import SCHEMA, Base
from app.schema_filter import include_object

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def database_url() -> str:
    """The database to migrate.

    `alembic -x database_url=...` wins, so a scratch database can be migrated without rewriting
    the process environment; otherwise this is exactly the URL the application would use.
    """
    override = context.get_x_argument(as_dictionary=True).get("database_url")
    if override:
        return override
    return get_settings().database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Emit the migration SQL instead of running it (`alembic upgrade head --sql`)."""
    # Nothing executes in this mode, so the schema statement is written straight into the script,
    # ahead of everything alembic emits — including its own version table. ensure_schema() below
    # explains why that order is the whole point.
    buffer = config.output_buffer or sys.stdout
    buffer.write(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA};\n\n")

    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=SCHEMA,
        include_schemas=True,
        include_object=include_object,
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def ensure_schema(connection: Connection) -> None:
    """Create the `admin` schema if this is an empty database.

    Alembic creates its version table in version_table_schema *before* the first revision's
    upgrade() runs, so on a fresh database the schema has to exist a moment earlier than the
    revision that owns it would create it. Both statements are IF NOT EXISTS and both are
    honest: the revision still creates the schema on any path that reaches it first.
    """
    connection.execute(CreateSchema(SCHEMA, if_not_exists=True))
    connection.commit()


def run_migrations_online() -> None:
    """Run the migrations against a live database."""
    engine = create_engine(
        database_url(),
        # One connection, used once, then the process exits. A pool would only be something to
        # shut down.
        poolclass=pool.NullPool,
    )

    with engine.connect() as connection:
        ensure_schema(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=SCHEMA,
            include_schemas=True,
            include_object=include_object,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()

    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
