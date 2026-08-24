# substate-admin

[![CI](https://github.com/umbrella-at/substate-admin/actions/workflows/ci.yml/badge.svg)](https://github.com/umbrella-at/substate-admin/actions/workflows/ci.yml)

An admin panel for [substate](https://github.com/umbrella-at/substate) — tables, roles, and a time
machine that fast-forwards subscription lifecycles in front of you.

## Status

The delivery path is live: every merge to `main` lints and type-checks the backend, runs its suite
against a real Postgres, ships to a single origin behind Caddy, migrates the database, restarts the
API, verifies the release over the public https URL, and rolls the symlink back to the previous
release if that check fails. It was built and proven before there was any application code to blame
when it broke.

The backend is written. FastAPI on async SQLAlchemy over PostgreSQL 18, Alembic migrations into a
dedicated `admin` schema, and the authentication described below: argon2id passwords, 15-minute
access tokens, rotating refresh tokens with reuse detection, and permissions read from the database
on every request rather than carried in the token. It serves `/api/health`, `/api/auth/*` and
`/api/users`, and a CLI is how the first administrator comes to exist.

What the site serves at `/` is still a placeholder page. The Vue frontend — a login screen and one
protected route to begin with — is next, and the screenshot in this README arrives with it.

## Stack

| Area       | Choice                                                                    |
| ---------- | ------------------------------------------------------------------------- |
| Frontend   | Vue 3.5, TypeScript (strict), Vite, Pinia (auth state only), TanStack Query and TanStack Table, Tailwind v4 |
| Backend    | FastAPI, SQLAlchemy 2 (async, on psycopg 3), Alembic, argon2id, structlog  |
| Database   | PostgreSQL 18                                                             |
| Serving    | Caddy, one origin: the SPA at `/`, the API at `/api` with the prefix intact |
| CI/deploy  | GitHub Actions — every push: shellcheck, `caddy validate`, ruff, mypy and pytest against a Postgres 18 service container. On `main`: rsync, `uv sync --frozen`, `alembic upgrade head`, atomic symlink swap, service restart, and an https smoke test on `/api/health` that asserts the deployed commit, with rollback |

## Design note: authentication

This is what the backend implements. It is written down here because it is the one part of the
project where the interesting decisions are not obvious from the code.

The access token is a JWT with a 15-minute lifetime, kept in memory in the JS heap and never in
`localStorage` or `sessionStorage`. The refresh token lives in an httpOnly, Secure, `SameSite=Lax`
cookie scoped to `Path=/api/auth`. A family is one device's chain of tokens, minted at login,
capped at ninety days and never extended. It rotates on every exchange: presenting a refresh token
returns a new one and marks the old as used. Presenting an already-used token outside the window
below is treated as theft, and revokes every family the user has — not just the one that leaked,
because nothing about a copied secret says which device it was copied from.

**The 30-second grace window.** Strict reuse detection punishes honest clients. A single shared
refresh promise only dedupes requests inside one JS context; a page reload while a refresh is in
flight, a second tab waking up, or a network-level retry all legitimately present the same token
twice, and none of them are an attacker. So a spent token stays exchangeable for thirty seconds:
presenting it again within 30 seconds of the moment it was spent — its `used_at`, or, for a token
that some other rotation replaced, the moment it was superseded — rotates it once more inside the
same family instead of killing it. Every rotation, the grace ones included, revokes whatever leaf
it replaces, because a family holding two live tokens is two sessions that never collide, which is
a family in which reuse can no longer be detected at all.

Outside that window it is theft: every family that user has is revoked, not only the one the
token came from. Nothing the client does closes the window early — its next exchange presents the
successor, never the token that successor replaced, so neither timestamp on a spent token ever
moves and only the clock ends its window. That is also how a theft committed inside the window
still surfaces. The attacker's replay is answered with a live token, but it supersedes the copy
the victim's browser is holding, and the victim's own next refresh — fifteen minutes later, when
the access token expires — presents that copy well outside the window and trips the cascade.
Thirty seconds is short enough for that to be the normal outcome of a stolen token and long
enough that flaky wifi does not log people out.

A revoked token is not by itself evidence of theft, and the reason it was revoked is what decides
the answer. A logout, a deactivated account, or a family caught in some other device's cascade is
a session that ended for a reason of its own: presenting one of those is refused and revokes
nothing further, because a cascade on every sibling of an already-revoked family would log the
user out of the session they had just signed back into. Every grace hit is logged as a warning,
so a client that lives permanently inside the window is visible rather than merely tolerated.

**No `__Host-` cookie prefix, on purpose.** `__Host-` requires `Path=/`, which would attach the
refresh token to every single API request — hundreds of chances a day for it to leak into a log, a
proxy, or an error report — so the narrower `Path=/api/auth` wins and the prefix is the price.

**One uvicorn worker, deliberately.** Not a sizing decision. The login rate limiter is in-memory,
and the world registry — the state behind the time machine — is in-memory too. Both are
correct only in a single process. Scaling out would mean moving that state to Redis or Postgres
first, not adding `--workers`.

## What this is not

- **Not a second product.** It exists to show what [substate](https://github.com/umbrella-at/substate)
  can do. Every decision here is settled in substate's favour.
- **Not a payment gateway.** It never touches money, never talks to a payment provider, and stores
  no card data. Subscriptions here are state machines, not invoices.
- **Not a billing panel for a real business.** It is not hardened, audited, or supported for
  production operation, and it is not intended for it.
- **Not a dashboard of decorative charts.** There is no chart in this project that is not backed by
  a real substate event.

## Repository layout

```
backend/            the API
  app/              config, lazy engine, models, permission catalogue, errors, logging, schemas
  app/security/     passwords, access tokens, refresh-token rotation, rate limiting
  app/routers/      health, auth, users — mounted under /api by the application, not by Caddy
  app/cli.py        substate-admin create-user | sync-permissions | prune-tokens
  alembic/          migrations; every table lives in the `admin` schema
  tests/            pytest against a real Postgres, each test inside a transaction that rolls back
frontend/           Vue 3.5 SPA, built in CI and never on the server        (not yet written)
deploy/             provisioning script, systemd unit, Caddyfile, and the placeholder page
docker-compose.yml  PostgreSQL 18 for local development, and nothing else
```

## Run it locally

Docker for Postgres, [uv](https://docs.astral.sh/uv/) for everything else — it fetches the
interpreter the project pins, so there is no Python to install first.

```sh
docker compose up -d                       # PostgreSQL 18 on 127.0.0.1:5432

cd backend
cp .env.example .env                       # then fill it in; see below
uv sync                                    # interpreter, dependencies, .venv
uv run alembic upgrade head                # the admin schema and its five tables
uv run substate-admin sync-permissions     # the permission catalogue and the system roles
uv run substate-admin create-user --email you@example.com --role admin
uv run uvicorn app.main:app --reload       # http://127.0.0.1:8000/api/health
```

For `.env`: `DATABASE_URL=postgresql+psycopg://postgres:postgres@127.0.0.1:5432/substate_admin`,
`JWT_SECRET` and `IP_HASH_PEPPER` from `openssl rand -hex 32`, `APP_ENV=development` — which also
publishes `/api/docs` — and `COOKIE_SECURE=false`, because Safari rejects a `Secure` cookie on
`http://localhost` without saying so and login appears to work right up until the first refresh.

`create-user` reads the password from the terminal, or from stdin when it is piped, and applies the
same policy any future write endpoint will: at least 12 characters, at most 128, and never the
local part of the address. `sync-permissions` is idempotent and is what the deploy runs after every
migration. `prune-tokens` is the reaper: nothing else in the backend ever deletes a
`refresh_tokens` row, so it is what keeps the one table that grows with traffic from growing
without end. It removes the rows that have been unexchangeable for more than a week — the week is
retention, not caution, because an expired row is the evidence behind a reuse alarm and is worth
keeping while somebody might still be reading one — reports how many went, and takes nothing any
client is holding, so running it twice is a no-op. Schedule it once a day from cron or a systemd
timer rather than from the service, which would sweep once per worker.

The suite wants a database of its own — it deletes users, and it should not be the last thing to
run against yours:

```sh
docker compose exec postgres createdb -U postgres substate_admin_test
cd backend && uv run pytest
```

That `createdb` says nothing about locale on purpose. It copies `template1`, which the compose file
created with the builtin provider and `C.UTF-8` — the same settings `deploy/provision.sh` gives the
production database, so `ORDER BY` means one thing on a laptop, in CI and on the server. Point the
suite somewhere else with `TEST_DATABASE_URL`; when nothing answers it stops the run rather than
skipping, because an authentication suite that reports "no tests ran" is a green build that proved
nothing.

## Licence

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Andrei Tarunin.
