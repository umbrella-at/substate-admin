# Design tokens

Written before the first line of UI code, and binding on it. Anything that needs
a colour, a size or a corner takes it from here. A component that reaches for a
value not on this page is a bug in the component or a gap in this file, and both
are fixed here first.

One theme, dark. A light theme is not v0.1.

## Surfaces

| Token | Value | Where |
|---|---|---|
| `--surface-0` | `#111820` | page background |
| `--surface-1` | `#18212B` | panels, table body, cards |
| `--surface-2` | `#1F2A36` | dialogs, popovers, dropdown menus |
| `--border` | `#263241` | default hairline, `0.5px` |
| `--border-strong` | `#32414F` | control outlines, hover |

Three surfaces and no more. A fourth level means the layout is nested too deep,
not that the palette is short.

## Text

| Token | Value | Where |
|---|---|---|
| `--text-primary` | `#E3EAF2` | body, table cells, headings |
| `--text-secondary` | `#A9B8C7` | labels, secondary controls |
| `--text-muted` | `#7C8B9C` | column headers, timestamps, hints |

Never dim text with `opacity`. Opacity multiplies against whatever is behind it
and drifts between surfaces; these three tokens hold their contrast everywhere.

## Accent

One accent, blue, and it is quiet on purpose.

| Token | Value | Where |
|---|---|---|
| `--accent-fill` | `#2C5F87` | the filled button |
| `--accent-fill-hover` | `#34719F` | its hover |
| `--on-accent` | `#E8F1F8` | text on the fill |
| `--accent-text` | `#5F94BF` | links, active icons, focus ring |
| `--accent-bg` | `#1B3549` | tinted accent surface, selected row |

**At most one filled accent element per screen.** On the subscriber card that is
the primary operation; on a plan form it is `Save`; in the time machine it is the
month jump. Everything else is outlined or plain. This is the rule that makes the
important action findable without any other decoration, and it stops working the
moment there are two.

## Controls

Inputs are recessed, buttons are raised. That is the whole system, and it only works if inputs
have something to be recessed *into*.

| Token | Value | Where |
|---|---|---|
| `--fill-disabled` | `#1E2831` | any control that cannot be used |
| `--text-disabled` | `#566472` | its label |

**An input always sits inside a `--surface-1` container or higher.** Its own fill is
`--surface-0`, so it reads as a well cut into the panel around it. Laid directly on the page
background it would match it exactly and survive as a rectangle of border — technically visible,
practically invisible. If a form has nowhere to live, the answer is a panel, not a fourth surface.

| Part | Token |
|---|---|
| fill | `--surface-0` |
| border | `--border-strong` |
| text | `--text-primary` |
| placeholder | `--text-muted` |
| border, in error | the `danger` role's border |
| message, in error | the `danger` role's text |

Focus is described under Floor and needs no token of its own.

The disabled tokens are deliberately neutral rather than accent-tinted. More than one kind of
control gets disabled — an outlined button, a text field, a checkbox — and none of those has an
accent fill to dim in the first place.

**Disabled is for an action that is unavailable, never for one that is in progress.** A button
waiting on a request keeps its colours and changes its label: `Sign in` becomes `Signing in…`,
carries `aria-busy`, and refuses a second submit in its handler. A two-hundred-millisecond request
that greys a button and un-greys it reads as a flinch, and it decides with colour something the
text already says.

## Subscription states

Five states, five chips, and they have to be told apart out of the corner of the
eye. `GRACE` means a paying customer is in arrears and someone should call today;
`EXPIRED` means it is over and there is nothing to do. If those two ever read as
shades of one colour, the table has stopped working.

| State | Background | Text |
|---|---|---|
| `TRIAL` | `#2C2550` | `#C2B4F5` |
| `ACTIVE` | `#123B2C` | `#6ED9A8` |
| `GRACE` | `#43300D` | `#F3BE5E` |
| `EXPIRED` | `#242F3B` | `#8C9BAB` |
| `CANCELLED` | `#43202D` | `#F08FA8` |

Chips: `12px`, radius `999px`, padding `2px 9px`, no border, no uppercase
transform — the state names are already uppercase in the domain.

**The round shape belongs to these five and to nothing else.** It is how a subscription state is
recognised before it is read, and every other pill on screen would spend that recognition.

A label that states a fact rather than a state — a permission code, a tag, a count — is a
different object and looks like one:

| Part | Value |
|---|---|
| background | `--surface-2` |
| text | `--text-secondary` |
| radius | `6px` |
| size | `12px`, mono |
| padding | `3px 8px` |

Mono because these are compared down a column: `subscribers.read` against `subscribers.write` is
a comparison of endings, and proportional letterforms make two codes of the same length look
different lengths.

## Semantic roles

| Role | Background | Text | Border |
|---|---|---|---|
| success | `#123B2C` | `#6ED9A8` | `#1D5B44` |
| warning | `#43300D` | `#F3BE5E` | `#6B4E15` |
| danger | `#47211F` | `#F0837E` | `#6E3330` |

Success and warning deliberately share their colours with `ACTIVE` and `GRACE`:
green is good and amber wants attention in both registers.

Danger does not share with `CANCELLED`. Danger is red-orange, `CANCELLED` is
rose. A destructive confirm dialog and a cancelled subscription must not look
like the same thing.

## Typography

IBM Plex Sans and IBM Plex Mono. One family, two cuts, self-hosted so nothing
depends on a font CDN being reachable.

Two weights only, `400` and `500`. Weight `600` and above reads heavy against
these surfaces.

| Role | Family | Where |
|---|---|---|
| ui | IBM Plex Sans | everything by default |
| numeric | IBM Plex Mono | dates, amounts, ids, model time, event payloads |

Anything a person compares down a column goes in mono: money, `expires_at`, user
ids. Proportional digits make two amounts of the same length look different.
Table cells also carry `font-variant-numeric: tabular-nums`.

| Size | Use |
|---|---|
| `12px` | column headers, chips, captions |
| `13px` | table cells, dense controls |
| `14px` | default UI text, form fields, buttons |
| `16px` | section headings |
| `20px` | page title |

Sentence case throughout. No `ALL CAPS`, no Title Case except proper nouns.

## Spacing

Base 4. The whole scale: `4 · 8 · 12 · 16 · 24 · 32 · 48`. No value off this
scale, and no `13px` because something looked slightly off — that means the wrong
step was chosen next to it.

| Radius | Where |
|---|---|
| `6px` | buttons, inputs, small controls |
| `8px` | panels, table container, chart frames |
| `12px` | cards, dialogs |
| `999px` | state chips only |

## Loading

A block that is waiting for data shows its own shape, not a spinner in the middle of the page.

| Token | Value |
|---|---|
| `--skeleton-base` | `#1F2A36` |
| `--skeleton-highlight` | `#26313D` |

The pulse runs `1.6s ease-in-out alternate` **between the two fills**, never through `opacity` —
for the reason the text section already gives: opacity multiplies against whatever is behind it
and drifts between surfaces.

Under `prefers-reduced-motion` the skeleton does not pulse. It stays flat on `--skeleton-base`,
which is still visibly a placeholder.

## Layout

Sidebar `240px`, fixed. Content fills the rest with `24px` page padding.

Tables are the widest thing in the application and are allowed to be: no content
max-width, horizontal scroll on the table container rather than truncation of
columns that matter.

Table row `40px`, header row `34px`, `14px` horizontal cell padding.

## Signature element

Left deliberately empty. The time machine control is where this interface spends
its boldness, and it is described here once it exists rather than imagined in
advance. Everything around it stays quiet so that it is the thing a visitor
notices.

## What this is not

Three looks are avoided on purpose, because they are what gets produced by
default and they read as such:

- cream background near `#F4F1EA`, a high-contrast serif, a terracotta accent
- near-black background with a single acid accent
- newspaper layout: hairline rules, zero radius, columns of small caps

Judge new screens against this list before adding anything decorative.

## Floor

Not features, not announced anywhere, simply true:

- responsive down to a phone; the table degrades to horizontal scroll, not to a
  card list that hides columns
- visible keyboard focus everywhere: `2px solid var(--accent-text)`, offset `2px`
- `prefers-reduced-motion` respected; no transition longer than `200ms` in any case.
  That ceiling is about transitions BETWEEN states — a hover, a panel opening, a chip changing
  colour. A loading animation is not a transition and keeps its own timing, described under
  Loading; holding it to 200ms would produce a strobe
- every colour pair above meets WCAG AA for its text size
