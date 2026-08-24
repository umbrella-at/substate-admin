# substate-admin

[![CI](https://github.com/umbrella-at/substate-admin/actions/workflows/ci.yml/badge.svg)](https://github.com/umbrella-at/substate-admin/actions/workflows/ci.yml)

An admin panel for [substate](https://github.com/umbrella-at/substate) — tables, roles, and a time
machine that fast-forwards subscription lifecycles in front of you.

## Status

The delivery path is live: every merge to `main` builds in CI, ships to a single origin behind
Caddy, verifies the release over the public https URL, and rolls the symlink back to the previous
release if that check fails. What it currently serves is a placeholder page — that is deliberate,
the delivery path is proven before there is any application code to blame when it breaks.

The application itself is next: the FastAPI backend with Postgres, Alembic and authentication, then
the Vue frontend with a login page and one protected route. There is no screenshot in this README
and no install instructions, because there is nothing to photograph and nothing to run yet. Both
arrive with the code they describe.

## Stack

| Area       | Choice                                                                    |
| ---------- | ------------------------------------------------------------------------- |
| Frontend   | Vue 3.5, TypeScript (strict), Vite, Pinia (auth state only), TanStack Query and TanStack Table, Tailwind v4 |
| Backend    | FastAPI, SQLAlchemy 2 (async), Alembic                                    |
| Database   | PostgreSQL 18                                                             |
| Serving    | Caddy, one origin: the SPA at `/`, the API at `/api` with the prefix intact |
| CI/deploy  | GitHub Actions — today: shellcheck and `caddy validate` on every push, then build, rsync, atomic symlink swap and an https smoke test with rollback on `main`. Lint, type-check, tests and `alembic upgrade` join as the backend and frontend land |

## Design note: authentication

The shape below is fixed and is what the backend implements once it lands. It is written down here
because it is the one part of this project where the interesting decisions are not obvious from the
code.

The access token is a JWT with a 15-minute lifetime, kept in memory in the JS heap and never in
`localStorage` or `sessionStorage`. The refresh token lives in an httpOnly, Secure, `SameSite=Lax`
cookie scoped to `Path=/api/auth`. It rotates on every exchange: presenting a refresh token returns
a new one and marks the old as used. Presenting an already-used token is treated as theft and
revokes the entire token family — every descendant of that original login.

**The 30-second grace window.** Strict reuse detection punishes honest clients. A single shared
refresh promise only dedupes requests inside one JS context; a page reload while a refresh is in
flight, a second tab waking up, or a network-level retry all legitimately present the same token
twice, and none of them are an attacker. So: within 30 seconds of a token's `used_at`, and only
while its family is still alive, presenting it again rotates it inside the same family instead of
killing it. Outside that window, or after the family has been revoked, it is theft and the family
dies. The window is short enough that a stolen token is worth very little and long enough that
flaky wifi does not log people out.

**No `__Host-` cookie prefix, on purpose.** `__Host-` requires `Path=/`, which would attach the
refresh token to every single API request — hundreds of chances a day for it to leak into a log, a
proxy, or an error report. The narrower `Path=/api/auth` means the browser only sends it to the two
endpoints that have any business seeing it. That is the better trade, and giving up the prefix is
the price.

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
backend/    FastAPI app, async SQLAlchemy models, Alembic migrations, tests   (not yet written)
frontend/   Vue 3.5 SPA, built in CI and never on the server                  (not yet written)
deploy/     provisioning script, systemd unit, Caddyfile, and the placeholder page
```

`backend/` and `frontend/` do not exist yet. The deploy pipeline that will carry them does.

## Licence

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Andrei Tarunin.
