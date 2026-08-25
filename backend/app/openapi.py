"""Write the OpenAPI schema to a file, so the frontend's types can be generated from it.

Run as `python -m app.openapi`. The frontend reads the committed backend/openapi.json rather than
a running server: a generator that needs the API up cannot run in the job that decides whether the
API is correct, and it turns a type check into an integration test.

The command deliberately needs no configuration. Building the app touches the database only if
something connects at import time, and nothing does — so the required secrets are filled with
obvious placeholders when absent. They never leave this process, and none of them reaches the
schema; the alternative is a CI job that either holds production-shaped secrets or cannot run.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_PLACEHOLDERS = {
    "DATABASE_URL": "postgresql+psycopg://schema:schema@127.0.0.1:5432/schema",
    "JWT_SECRET": "openapi-schema-generation-only",
    "IP_HASH_PEPPER": "openapi-schema-generation-only",
    # Not "production": the schema should describe every route the app can serve, and production
    # hides the docs endpoints. It does not change the paths themselves, but stating the intent
    # here keeps a future reader from discovering it by diffing.
    "APP_ENV": "development",
}

DEFAULT_OUTPUT = Path(__file__).resolve().parent.parent / "openapi.json"


def schema() -> dict[str, Any]:
    for key, value in _PLACEHOLDERS.items():
        os.environ.setdefault(key, value)
    from app.main import app

    return app.openapi()


def render() -> str:
    # sort_keys and a trailing newline: the file is compared with `git diff --exit-code`, so its
    # byte layout has to depend on the routes and nothing else — not on dictionary ordering, and
    # not on whether the last write happened to add a newline.
    return json.dumps(schema(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else list(argv)
    output = Path(args[0]) if args else DEFAULT_OUTPUT
    output.write_text(render(), encoding="utf-8")
    print(f"wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
