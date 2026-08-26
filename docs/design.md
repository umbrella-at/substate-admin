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
| `--text-muted` | `#8695A6` | column headers, timestamps, hints |

Never dim text with `opacity`. Opacity multiplies against whatever is behind it
and drifts between surfaces; these three tokens hold their contrast everywhere.

## Accent

One accent, blue, and it is quiet on purpose.

| Token | Value | Where |
|---|---|---|
| `--accent-fill` | `#2C5F87` | the filled button |
| `--accent-fill-hover` | `#34719F` | its hover |
| `--on-accent` | `#E8F1F8` | text on the fill |
| `--accent-text` | `#6B9EC7` | links, active icons, focus ring |
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
| `--control-border` | `#657787` | the boundary of anything a person operates |
| `--fill-disabled` | `#1E2831` | any control that cannot be used |
| `--text-disabled` | `#566472` | its label |

`--control-border` is separate from `--border-strong` and replaces it on every control. A field's
border is not decoration here: its fill is `--surface-0` and the panel around it is `--surface-1`,
which differ by 1.09:1, so the border is the entire visual evidence that a field exists. It is
measured on every surface it can appear on — 3.86:1 on `--surface-0`, 3.52:1 on `--surface-1`,
3.15:1 on `--surface-2` — because a boundary visible from one side is half a boundary, and a
control inside a dialog is still a control.

`--border-strong` keeps the work that does not carry that weight: a panel's hover, a divider
inside a control. Nothing depends on seeing it.

Yes, fields are more visible than a mockup would draw them. That is the correct direction: on a
dark interface the temptation is to let controls dissolve into the surface, and a field nobody can
find is not restrained, it is broken.

**An input always sits inside a `--surface-1` container or higher.** Its own fill is
`--surface-0`, so it reads as a well cut into the panel around it. Laid directly on the page
background it would match it exactly and survive as a rectangle of border — technically visible,
practically invisible. If a form has nowhere to live, the answer is a panel, not a fourth surface.

| Part | Token |
|---|---|
| fill | `--surface-0` |
| border | `--control-border` |
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

Chips: `12px`, radius `999px`, padding `3px 9px`, no border, no uppercase
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
| padding | `3px 9px` |

Mono because these are compared down a column: `subscribers.read` against `subscribers.write` is
a comparison of endings, and proportional letterforms make two codes of the same length look
different lengths.

## Semantic roles

| Role | Background | Text | Border |
|---|---|---|---|
| success | `#123B2C` | `#6ED9A8` | `#1D5B44` |
| warning | `#43300D` | `#F3BE5E` | `#6B4E15` |
| danger | `#47211F` | `#F0837E` | `#6E3330` |

### Inline notice

One shape for all three roles. A login error, an expired-session banner and a failed panel are the
same object wearing different colours, and three different shapes would say they are not.

| Part | Value |
|---|---|
| radius | `6px` |
| padding | `8px 12px` |
| border | `1px`, the role's border colour |
| background | the role's background |
| text | the role's text colour, `13px` |
| icon | optional, `14px`, the role's text colour |

Width follows the container, never `--width-reading`: a notice belongs to the thing it is about, and
one that is narrower than the panel it sits in reads as unrelated to it.

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

The one exception, named here so it does not have to be argued again: **the padding inside a chip
is set optically from the type, not from this grid.** A chip is a box drawn around a single line
of 12px text, and its breathing room is a property of that line rather than of the layout it sits
in — `3px 9px` for both the state chips and the fact labels. Nothing else may leave the scale.

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
| `--skeleton-base` | `#3A4757` |
| `--skeleton-highlight` | `#47566A` |

The pulse runs `1.6s ease-in-out alternate` **between the two fills**, never through `opacity` —
for the reason the text section already gives: opacity multiplies against whatever is behind it
and drifts between surfaces.

Under `prefers-reduced-motion` the skeleton does not pulse. It stays flat on `--skeleton-base`
**and gains a `1px` outline in `--control-border`**, which is what makes it visible rather than
what makes it pretty: with the motion gone, the fill alone is 1.72:1 against the panel, and the
outline is 3.10:1 against that same panel. The earlier version of this paragraph asserted the flat
fill "is still visibly a placeholder", which was not true and was never measured — a reader who
had asked for less motion got an apparently empty panel instead of a loading one.

## Layout

Sidebar `240px`, fixed. Content fills the rest with `24px` page padding.

| Token | Value | Where |
|---|---|---|
| `--width-form` | `400px` | the login form, narrow forms, dialogs without a table |
| `--width-reading` | `672px` | reading text, empty states, explanations of an error |

Two widths, because a form and a paragraph want different measures and everything else was going
to invent its own. Tables have no maximum width, which is said below.

Tables are the widest thing in the application and are allowed to be: no content
max-width, horizontal scroll on the table container rather than truncation of
columns that matter.

**There are no shadows.** A layer that floats — a select's list, a menu, a dialog — is separated
by `--surface-2` against the surface beneath it and a `--border-strong` outline, and that is the
whole mechanism. A shadow on a dark theme is nearly invisible and would need a scale of its own to
be used consistently; one floating layer is not enough reason to have one.

**A control's height is not a number.** It comes from its vertical padding and the size of its
text: `py-2` on `--text-ui`. Not `h-9`, which would be a number arguing with the type scale rather
than following it — and which does not exist here anyway, the spacing namespace being closed. Two
controls of the same padding and the same type size are the same height by construction; where
they differ by a pixel or two because one is an `<input>` and one is not, they are aligned on
their bottom edge and the difference does not read.

**A control that opens a list is as wide as its content.** Not a fixed width, because there is no
width step here for "wider than the longest label" and inventing one is how a design file stops
being the place values come from. Placed at the end of its row, so it grows leftward into space
rather than pushing anything.

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

## What the build enforces

A design document that does not say which of its rules a machine checks is followed halfway within
a month, and nobody can tell which half. So:

**The build refuses these.** They are not conventions, they are compile errors.

| Rule | How |
|---|---|
| no colour outside this file | Tailwind's `--color-*` namespace is cleared; `bg-red-500` does not exist |
| no radius outside this file | `--radius-*` cleared; only control, panel, card and chip resolve |
| no type size outside this file | `--text-*` cleared; only the five named sizes resolve |
| no width outside this file | `--container-*` cleared; only `--width-form` and `--width-reading` resolve |
| no spacing step outside the scale | `--spacing-*` cleared; `p-5` does not exist |
| the round shape is for subscription states only | a CI grep for `rounded-full` outside the state-chip component |
| the fonts actually ship | CI counts `@font-face` rules in the built CSS |
| nothing loads from another origin | `scripts/assets.py` reads every `url()` and `@import` in the built CSS |
| every utility resolves to something | `scripts/utilities.py` fails on a class name that produced no CSS |
| every colour pair is measured | `scripts/contrast.py` runs in CI and fails on a pair below its requirement |

**Nobody checks these but a person.** They are the rules worth reading the diff for.

- at most one filled accent element per screen
- an input sits inside a `--surface-1` container or higher
- disabled is for an action that is unavailable, never for one in progress
- buttons named for what happens, sentence case throughout
- text dimmed with a token, never with `opacity`
- a skeleton in the shape of what is coming, not a spinner

`rounded-full` deserves a note: it survives even a cleared `--radius-*`, because Tailwind ships it
as a static utility rather than deriving it from the theme. The grep is the only thing standing
between this rule and the first avatar somebody adds.

**A cleared namespace fails in the other direction too, and that one is silent.** The first six
rows above are all the same mechanism — the value does not exist, so the utility asking for it
does not exist either. Tailwind does not warn about that. It emits no rule, and the element
renders with square corners, or with no height, or at its content width, while the source reads
correctly. Three real defects arrived that way, every one of them from a component generated
against Tailwind's stock scale and dropped into this project's smaller one:

| written | wanted | rendered |
|---|---|---|
| `rounded-2xl` | a radius this file does not have | square corners |
| `h-9` | `--spacing-9` | a control twenty pixels tall |
| `min-w-0` | `--spacing-0` | a flex child that would not shrink |

That is what `scripts/utilities.py` is for. It reads the class names the markup actually contains
— `class` attributes and string literals, comments removed — and fails on any that produced no
CSS. A closed namespace means a foreign vocabulary silently yields nothing; this is the thing that
notices, rather than an eye on a screenshot.

The same shape of silence is why `scripts/assets.py` exists. A generator that writes
`@import url('https://fonts.googleapis.com/…')` into this stylesheet costs nothing visible: the
panel's CSP refuses the request, the page renders on the fallback stack, and the `@font-face`
count stays green because a remote import contributes none. Everything the stylesheet loads has to
be bundled beside it.

## Floor

Not features, not announced anywhere, simply true:

- responsive down to a phone; the table degrades to horizontal scroll, not to a
  card list that hides columns
- visible keyboard focus everywhere: `2px solid var(--accent-text)`, offset `2px`
- `prefers-reduced-motion` respected; no transition longer than `200ms` in any case.
  That ceiling is about transitions BETWEEN states — a hover, a panel opening, a chip changing
  colour. A loading animation is not a transition and keeps its own timing, described under
  Loading; holding it to 200ms would produce a strobe
- **contrast is a requirement with numbers behind it, not a claim.** Text at any size in this
  interface needs 4.5:1 — the largest type here is 20px and WCAG's lower bar starts at 24px, so
  nothing here qualifies for it. The boundary of a control needs 3:1, per 1.4.11.

  Measured, so that the next change to the palette has something to fail against:

  | Pair | Ratio | Needs |
  |---|---|---|
  | `--text-primary` on `--surface-1` | 13.41 | 4.5 |
  | `--text-secondary` on `--surface-1` | 8.03 | 4.5 |
  | `--text-muted` on `--surface-0` | 5.84 | 4.5 |
  | `--text-muted` on `--surface-1` | 5.32 | 4.5 |
  | `--text-muted` on `--surface-2` | 4.76 | 4.5 |
  | `--accent-text` on `--surface-0` | 6.25 | 4.5 |
  | `--accent-text` on `--surface-1` | 5.68 | 4.5 |
  | `--accent-text` on `--surface-2` | 5.09 | 4.5 |
  | `--on-accent` on `--accent-fill` | 5.94 | 4.5 |
  | `--on-accent` on `--accent-fill-hover` | 4.58 | 4.5 |
  | `--control-border` on `--surface-0` | 3.86 | 3.0 |
  | `--control-border` on `--surface-1` | 3.52 | 3.0 |
  | `--control-border` on `--surface-2` | 3.15 | 3.0 |
  | `--skeleton-base` on `--surface-1` | 1.72 | carried by motion, or by the outline |
  | the reduced-motion outline on `--surface-1` | 3.52 | 3.0 |
  | state chip text on its own fill | 4.78 – 7.49 | 4.5 |
  | notice text on its own fill | 5.48 – 7.40 | 4.5 |
  | `--text-disabled` on `--fill-disabled` | 2.47 | exempt: 1.4.11 excludes inactive components |

  A chip's tinted fill, a notice's border and a table hairline are measured by
  `scripts/contrast.py` and deliberately not required to reach 3:1. None of them is what
  identifies its component — the text is, and the text is measured above. Holding a state chip's
  fill to 3:1 against the panel would produce five chips the colour of the page.

  Three of these were short once, all on `--surface-2`, all for one reason: the palette had been
  checked against `--surface-0` and `--surface-1` and never against the surface above them — which
  is where dialogs, popovers and dropdown menus go. The fix was to lift `--text-muted`,
  `--accent-text` and `--control-border`, not to darken `--surface-2`: at the value that cleared
  4.5:1 the raised surface sat 1.02:1 from `--surface-1`, so a dialog stopped reading as raised
  and the three-surface system stopped meaning anything. Every number above is now measured on all
  three surfaces, which is the habit that catches this class of thing rather than the one fix.
