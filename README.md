# substate-admin

[![CI](https://github.com/umbrella-at/substate-admin/actions/workflows/ci.yml/badge.svg)](https://github.com/umbrella-at/substate-admin/actions/workflows/ci.yml)

An admin panel for [substate](https://github.com/umbrella-at/substate): subscriptions as states rather than invoices, for whoever has to answer what is happening to an account — and for whoever is deciding whether the library is worth building on.

![A stranger presses Try the demo, lands in a world of their own, and winds it forward three months: the clock moves, subscriptions cross between states, and the chips change colour under it](docs/demo.gif)

![The subscriber table: state chips, server-side filters, and paging through 351 people](docs/subscribers.png)

![One subscriber in grace: the two boundaries that state has, the operations available on it, and the events behind them](docs/subscriber.png)

![Five figures: arrivals against departures by week, where the funnel loses people, the five states standing now, how long the quiet have been quiet, and revenue by month](docs/analytics.png)

Every picture here is generated rather than taken. `npm --prefix frontend run capture` drives a running copy, frames the same windows every time and overwrites the files above. Each run asserts what it recorded — three of the five states in the table, both boundaries and every operation on the card, five drawn plots and no skeletons on the analytics screen, and for the recording, a subscriber who is in a different state at the end of it than at the start. A picture that has quietly got worse is a failed run rather than a discovery in the README.

## Live

<https://substate-admin.umbrella-at.uk>, and there is a **Try the demo** button on the sign-in screen. Pressing it builds a world of its own — nine months of invented history, an hour to live, its own clock — and walks straight into the panel with it. Nothing you do there is real and nothing leaves it.

`/api/health` needs no account either, and answers with the release that is serving and the world behind it:

```json
{ "status": "ok", "version": "0.1.0", "commit": "840edf8", "db": true,
  "world": { "id": "base", "seeded": true, "subscribers": 351, "events": 3791 } }
```

## Run it locally

Docker for Postgres, [uv](https://docs.astral.sh/uv/) for the backend — it fetches the interpreter the project pins, so there is no Python to install first — and Node 24, which `.nvmrc` names.

Three commands, from the repository root:

```sh
docker compose up -d                                       # PostgreSQL 18 on 127.0.0.1:5432
uv run --directory backend uvicorn app.main:app --reload   # http://127.0.0.1:8000/api/health
npm --prefix frontend run dev                              # http://127.0.0.1:5173
```

The API builds the demonstration world while it starts, so the second command is also the one that produces the 351 subscribers.

First time, before those three work — the schema, the permission catalogue, an account to sign in as, and the dependencies the SPA is built from. The database has to be up before the migration, and the configuration has to be filled in before either, so the order below is the order it runs in:

```sh
docker compose up -d                   # the database the migration is about to talk to
cp backend/.env.example backend/.env   # then fill it in: three keys have no defaults and
                                       # nothing starts without them
uv run --directory backend alembic upgrade head
uv run --directory backend substate-admin sync-permissions
uv run --directory backend substate-admin create-user --email you@example.com --role admin
npm --prefix frontend ci
```

The three with no defaults are the DSN and two secrets, and the file describes every key it holds. With the compose file above, the DSN is `postgresql+psycopg://postgres:postgres@127.0.0.1:5432/substate_admin`; both secrets are whatever `openssl rand -hex 32` gives you.

`COOKIE_SECURE=false` is the one that catches people: Safari refuses a `Secure` cookie over `http://localhost` without saying so, and the panel logs in and then cannot refresh.

The browser tests sign in as three fixed accounts of their own and need a role the panel does NOT define: the sharper half of the permission scenario asserts that the controls on a role are absent, and every role the deploy defines hides them from everybody, so asserting it there would pass with the permission check deleted. The addresses are literals in `playwright.config.ts`, so the account you created above is not one of them:

```sh
uv run --directory backend substate-admin create-role \
  --code e2e-analysts --name Analysts --grant analytics.read
printf 'playwright-local-password\n' | uv run --directory backend \
  substate-admin create-user --email e2e@substate-admin.test --role admin
printf 'playwright-local-password\n' | uv run --directory backend \
  substate-admin create-user --email e2e-viewer@substate-admin.test --role viewer
printf 'playwright-local-password\n' | uv run --directory backend \
  substate-admin create-user --email e2e-support@substate-admin.test --role support
```

Everything CI checks, in one command:

```sh
./scripts/gate.sh
```

It exits `0` when every check ran and passed, `1` when one failed, and `2` when one could not run at all — no database, no API, no docker. A gate that quietly skipped those would report success for a run that proved less than the last one.

## What it does

**Worlds, each with its own clock.** Every read of subscription data goes through a world: its own `substate` engine, its own storage, its own clock. That clock is real time with an offset laid over the top, and it only ever moves forward — backwards is refused rather than clamped, because a subscription's due date is compared against now and moving now backwards reaches states the engine could never have arrived at by itself. A world nobody is looking at keeps running: a background tick every thirty seconds advances whatever has come due.

**A seeder that runs the engine.** Nine months of a subscription service, produced at every start by running `substate` forward through 274 days rather than by inserting rows that look like a history. The section below is about that run.

**An event journal.** Every event that run emitted — around 3,700 of them — lands in Postgres keyed to the world it belongs to, written with `COPY` in the same transaction that deletes the previous build. The world is rebuilt at every start, so the journal is replaced rather than appended to, and a month of ordinary deploys does not leave half a million rows of dead history behind.

**A world of your own, for an hour.** The demonstration door builds a sandbox per visitor: its own engine, its own clock, its own operators and roles, seeded from the same nine months and thrown away when the hour is up. Thirty-two of them stand at once, ten may be opened from one address in fifteen minutes, and a restart takes every one of them with it — worlds live in memory, so a pass whose world is gone gets the screen written for that rather than a sign-in page it has no account for.

**The time machine, in the frame rather than in a settings page.** A subscription engine's whole subject is time passing, and a panel over one that cannot move time is a set of screenshots. A day, a week, a month or a number of days, forward only, up to a year per world; every figure and every table on screen is re-read from the clock it moves. It is where this interface spends its boldness, and `docs/design.md` describes it down to the pixel.

**The subscriber table.** Five states, five plans, three cohorts, a search box, sorting and paging — all answered by the server, which sends a page of twenty-five rather than three hundred rows for the browser to sift. The state of a subscription is asked of the engine on every request; only the display name and the last time somebody turned up come from the projection, and nothing caches the first kind into the second.

**The question lives in the URL.** Filters, sort and page are read out of the address and written back to it, and nothing keeps a second copy. So everybody in grace is a link that can be sent to a colleague rather than a route described over a call, the back button walks the filters somebody actually used, and a reload gives the same table back.

**One subscriber's card, with the boundaries that state has.** A subscription has three of them — the end of a trial, the end of a paid period, the end of the courtesy after it — and no state has all three. The card draws the ones this state owns and no others, which is a type rather than a convention: the flat wire shape is narrowed once into a union whose grace arm is the only one that has a grace end, consumed by a switch with no default. A dash appears in exactly one place, and it is the place the table already uses one: a subscription that ended without a payment ever being made.

**Six operations, and the rule that decides which of them ask first.** An operation is confirmed when a person cannot reverse its effect with another operation on the same card, and the consequence is not already stated by what they typed. That gives a dialog to cancelling, to starting a new subscription and to redeeming a code — none of which anything can undo — and none to recording a payment, changing a plan or assigning a referral programme, each of which is idempotent or reverses itself. It is a rule rather than six opinions: it decides the seventh operation without a meeting, and it corrects the intuition that redeeming a code is generous and changing a plan is grave.

**What an operation says it did comes from the engine.** Three payment outcomes are a 200 and a subscription that did not move — a reference already on file, an amount short of the price, a payment against a cancelled record — so the notice is rendered from the events that came back rather than from the button that was pressed, in the colour those events earned. And a refusal arrives under the exception's own name: `PROMO_ALREADY_BOUND`, `UNKNOWN_PLAN`, `ALREADY_SUBSCRIBED` reach the browser as codes, and the ones about a value somebody typed name the field, so the sentence lands under the input rather than in a banner above it.

**An audit of attempts, not successes.** Every operation that reached the engine is a row, refused ones included — because the engine catches a subscription up with the clock *before* it decides to refuse, so a refused call can be the cause of a state change the event journal does record, and because "who tried to cancel this and was told no" is the question an audit is opened for. It is deliberately narrow: signing in, signing out and changing a filter are authentication and navigation, and they belong in the structured log where they do not bury the handful of lines that say somebody changed something.

**Five figures, and one number that has to agree with the table.** Each asks a single question and says under it where its answer came from, because two sources sit behind them: the engine holds what is true now, the journal holds what happened. Only the state snapshot asks the table's own question of the table's own source, and it walks the engine through the same iterator the table does — so `sum(states) == subscribers.total` holds by construction rather than by two pieces of code agreeing. A test asserts it twice: on a fresh world, and after the clock has been wound forward forty-five days and the engine ticked.

**A funnel of three stages, because the fourth was not one.** The specification asked for arrived → trial → paid → renewed. Measured on the real history, the third stage stands taller than the second: a weekly plan has no trial days, so 72 of 351 arrivals are put straight in front of the first payment. Four descending bars would have shown the third one rising and read as a defect, so the trial is a sentence under the plot rather than a step in it.

**A departure is counted once.** `substate` gives a cancelled subscription's eventual expiry the reason `cancelled`, so "expired plus cancelled" — which is what the specification says — counts 76 of the base world's 485 departures twice. The outflow line counts a departure where it was decided.

**Roles and permissions out of the database, and edited from the panel.** The router and the navigation ask whether a permission is held, never which role holds it — roles are rows an administrator can edit, and keying the interface on role codes would mean a role change could only take effect with a frontend release. The catalogue is the backend's `permissions.py`, force-synced into the database on every deploy.

**A control nobody may press is not drawn, and the endpoint refuses it anyway.** Either half alone is a false comfort: a hidden button over an open endpoint is a panel that only looks locked, and a 403 under a button that is drawn is a panel offering a locked door. A browser test signs in as a `viewer`, asserts the section is absent from the menu and that `GET /api/roles` answers 403; then as `support`, who gets the screen, none of its controls, and a 403 on the write behind them. A system role is refused by the application too, and not merely hidden — the deploy restores it from the catalogue, so an accepted edit would be undone at the next push.

FastAPI on async SQLAlchemy over PostgreSQL 18, Vue 3.5 and TypeScript on Tailwind v4, and `schema.d.ts` generated from the backend's own OpenAPI document — both files committed, and CI fails when either stops matching the other.

## The history behind the numbers was not written by hand

The demonstration data is the part of a panel like this that is usually a lie. A few hundred rows of plausible-looking subscriptions get inserted by a script, and every screen built on top of them is a screen that cannot be wrong, because nothing in it was ever computed.

Here the history is produced by running the engine. At every start the panel creates a world whose clock sits 274 days in the past, and steps it forward day by day: people sign up, trials convert or lapse, payments arrive before a period ends and renew it, some arrive during the grace window and rescue it, some never arrive at all. Nothing writes a state: every state on the screen is one the engine reached by itself, and if it changes its mind about what a payment before a period ends means, this history changes with it.

**The run is deterministic.** One seed, one sequence of decisions, the same 351 people in the same order on every machine — and it costs about a seventh of a second, which is what lets it happen at every start rather than once into a fixture nobody regenerates. The clock it runs on is the one the panel uses, started at an offset of minus nine months and stepping to exactly zero: a negative starting offset is not a backwards move, so the fast-forward is exercised nine months' worth before anybody builds a control for it.

**The population is calibrated, and the calibration is the interesting part.** The behaviour that drives the run — arrivals ramping over the nine months, 26% of trials converting, 89% of active subscribers paying for the next period, 7% a day of the grace window ending in a payment, 7% a day of the expired coming back — was moved until the table at the end looked like a service somebody uses. The first run had 58% of subscribers expired and nobody at all in grace: a graveyard, with an empty filter on the one state the design says means *call today*. An earlier attempt at filling grace dropped renewal to 55%, which filled it by making the product fail — the median subscriber renewed twice, and seven in ten had lapsed at least once.

**A test asserts the ranges rather than the numbers.** Exact counts break on any change to the model and train you to edit the test instead of thinking; ranges catch the thing that matters, which is a population drifting out of the shape that makes the screen worth looking at.

**And a range is asserted of a size, not of a draw** — which took a red build to notice. Standing grace is the one population in single digits, so its value on any given day is a sample: the world is built ending *now*, and the same seed lands on a different calendar every day. Measured over 120 consecutive landing days it ran 0 to 8 around a mean of 3.1, so the floor of three the test held it to was below its own mean and failed on 38% of days — and the demonstration's *call today* filter was empty on one day in forty. The weekly plan, which renews thirty-nine times a year and so produces most of the missed payments, held them for two days; six days of courtesy puts the mean at 5.6 and leaves the filter empty on none of those 120 days. The test now asserts the mean over a week of landing days, which is what the calibration was ever a statement about.

Comments in the code say what breaks if the line beside them changes. The reasoning behind a decision is in the pull request that made it.

## What this is not

- **Not a second product.** It exists to show what [substate](https://github.com/umbrella-at/substate) can do. Every decision here is settled in substate's favour.
- **Not a payment gateway.** It never touches money, never talks to a payment provider, and stores no card data. Subscriptions here are state machines, not invoices.
- **Not a billing panel for a real business.** It is not hardened, audited, or supported for production operation, and it is not intended for it.
- **Not a dashboard of decorative charts.** Five figures, one question each, and every number on them counts events the engine actually emitted. There is no sixth, and there is no date picker: the design file refused one, so the period is a choice from three.

## What v0.1 deliberately leaves out

A boundary nobody wrote down gets re-drawn by whoever needs it next, so here is this one.

- **The catalogue is set in code and read by the panel.** Plans, promo codes and referral programmes are constants the API serves and every screen chooses from; editing them is v0.2, and so are the Plans, Promo codes and Referrals screens that would edit them. The forms, the tables, the permission matrix and the four states are all demonstrated by the six operations on a subscriber's card, and a fourth pass over the same ground would add nothing to read.
- **No general event feed.** A subscriber's own history is on their card. The whole journal as one screen is v0.2, with the catalogue screens.
- **No SQLAlchemy storage.** Worlds run on `substate`'s in-memory storage, which is why a restart takes every sandbox with it. Persistent storage is substate's own v0.2.
- **One theme, dark.** No light theme — `docs/design.md` says so on its first page — and no i18n or localisation: the interface is English, and the fonts it ships are subset to Latin.
- **No export and no print stylesheet.** Nothing here produces a CSV or a PDF.
- **No real payment provider.** A webhook shape is exercised in the tests and nothing outbound is wired to anything.
- **Nothing leaves the panel.** No notifications, no email, no outbound webhooks.
- **Responsive down to a phone and no further.** The floor in `docs/design.md` is met — the table scrolls sideways rather than hiding columns — and there is no separate mobile interface above it.
- **Multi-tenancy is the world mechanism and nothing more.** A sandbox is an isolation boundary for a demonstration, not an account model.

## Known limitations

Measured, not guessed, and left in on purpose rather than overlooked.

- **A full year of winding occupies the only worker for about 1.8 seconds.** The day loop has no suspension point in it, and adding one would be worse: reads are not served from a snapshot, so a request landing mid-wind would meet an engine two hundred days ahead of a projection that has not moved, and the quiet cohort and the default sort both read that projection. The bound that does exist is real — a year is a world's whole allowance, not a per-press cost, and it is one world at a time.

## substate

The engine this is a window onto: [github.com/umbrella-at/substate](https://github.com/umbrella-at/substate), `pip install substate`. Trials, renewals, grace periods, promo codes and referrals, with an injectable clock — which is why nine months of history here costs a seventh of a second.

## Licence

MIT — see [LICENSE](LICENSE). Copyright (c) 2026 Andrei Tarunin.
