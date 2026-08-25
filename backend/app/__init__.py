"""The substate-admin backend.

This module stays empty of imports on purpose. `import app` must not read configuration, build
an engine or open a socket, so alembic, the CLI and a bare test collection can load the package
on a machine that has neither a database nor a secret to its name.
"""

__version__ = "0.1.0"
