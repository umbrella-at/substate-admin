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
| `--scrim` | `rgba(0,0,0,0.55)` | behind a dialog |

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

**One exception, and it is not about text.** A region waiting for a newer answer to the question
already on screen — a table between two pages, a feed between two filters — is drawn at `opacity:
0.6` as a whole. What that says is "these rows are real and one question out of date", which is a
statement about the region rather than about any word in it; there is no token for it because a
token would be a colour, and the rows are not being made secondary, they are being made
provisional. It lasts as long as the request and is never a resting state, so nothing is read at
the reduced ratio for longer than a request takes — and the alternative, emptying a table that has
correct rows in it to show a placeholder, is the worse trade this file has already refused once.

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

## Cards

A card is a `--surface-1` panel with a `12px` radius. It is what a detail screen is made of, the
way a list screen is made of one table.

| Part | Value |
|---|---|
| fill | `--surface-1` |
| radius | `12px` |
| padding | `16px` |
| between rows inside a card | `12px` |
| between cards | `16px` |

`16px` inside against `24px` page padding, deliberately: a panel whose padding matches the page's
stops reading as a panel and starts reading as a region of the page. The `12px` between rows is
one step below both, so the rows group inside the card before the cards group on the page.

**A card has no maximum width.** It is not a form and not prose — it carries the event feed, and
the feed is a table, and tables here have no maximum. `--width-form` still governs the forms
inside it.

### A label and its value

The one shape for "here is a fact about this subscriber". Stacked, never side by side: a column of
labels down the left is a second grid to keep aligned, and the values are the thing being read.

| Part | Value |
|---|---|
| label | `12px`, `--text-muted` |
| value | `14px`, `--text-primary` |
| between them | `4px` |

The label takes the size and colour Typography already assigns to "column headers, timestamps,
hints", because that is what it is. The value takes the mono cut when it is something compared
down a column or against another value on the same screen — a date, an amount, an id, a plan id, a
promo code — which is the rule Typography already states, applied here.

### A value that is not there

Two different absences, two different marks, and the difference is the whole reason this section
exists:

- **A row the state does not have is not drawn.** A subscription in `ACTIVE` has no grace end —
  not an unknown one, none — so there is no row for it. Drawing `Grace ends —` would render a
  field the state does not have and teach the reader that active subscriptions have a grace end
  nobody filled in.
- **A row the state does have, with no value, shows `—`.** That is the mark the subscriber table
  already uses in `Access until`, for exactly one case: a subscription that expired without a
  payment ever having been made. The card and the table say the same thing about the same person.

One glyph, one meaning. A third convention — the word `None`, an empty cell — would make a reader
work out whether the difference is information.

**The card names each boundary for what it is** rather than collapsing them into one row. The
table has one date column and has to pick; the card has room and asks all three separately, which
is what the tagged union underneath it is for.

| State | Rows |
|---|---|
| `TRIAL` | Trial ends |
| `ACTIVE` | Expires |
| `GRACE` | Paid period ended · Grace ends |
| `CANCELLED` | Cancelled · Access ends |
| `EXPIRED` | Access ended (`—` when no payment was ever made) |

The label changes with the state on purpose. A fixed label over a date that means "paid until" in
one state and "missed on" in another is a stable position holding an unstable meaning, which is
the worse of the two trades.

### The one filled element on a subscriber card

Accent says at most one filled element per screen, and on this screen the filled one is **the
operation that would actually change something in the state the subscriber is in**:

| State | Filled |
|---|---|
| `TRIAL`, `ACTIVE`, `GRACE`, `EXPIRED` | Record a payment |
| `CANCELLED` | Start a subscription |

`CANCELLED` is not a preference. A payment against a cancelled subscription is filed and changes
nothing, so a filled `Record a payment` there would be the loudest control on the screen pointing
at the one thing that does nothing.

## Forms

| Part | Value |
|---|---|
| label | `12px`, `--text-secondary` |
| label to control | `8px` |
| control to the next field | `16px` |
| help text | `12px`, `--text-muted`, `4px` under the control |
| error text | `12px`, the `danger` role's text, `4px` under the control |

Help and error occupy the same place and never both at once: the error replaces the help while it
is on screen, so the control below never moves.

**Optional fields are marked `(optional)`; required ones carry nothing.** These forms are mostly
one required field, so marking the exception is fewer marks than marking the rule — and an
asterisk on nearly everything is a mark that stops being read.

Field faces follow Typography: the payment amount and a payment reference take the mono cut,
because both are compared against a value already on the card. A plan or a programme is chosen
from a list and is not compared to anything, so it takes the UI face.

## Dialogs

A dialog is for an action a person cannot undo from this screen. Everything else answers on the
press, and what it will do is said in the form, above the button, where the decision is being made
— a dialog asks after the decision has been taken.

| Part | Value |
|---|---|
| fill | `--surface-2` |
| radius | `12px` |
| padding | `24px` |
| width | `--width-form`, `400px` |
| title | `16px`, `--text-primary` |
| title to body | `12px` |
| body to actions | `24px` |
| actions | right-aligned, the confirming action last |
| edge | `1px` `--control-border` |
| behind it | `--scrim` |
| initial focus | the dismissing action |

**The scrim is not what makes the edge visible, and the arithmetic says so.** This palette lives
in a narrow band near the bottom of the scale, so darkening what is behind a dialog buys almost
nothing: `--surface-2` against the page reads 1.23:1 unscrimmed and 1.35:1 under this scrim,
and 1.39:1 even at 70% black. No scrim on this palette reaches 3:1. What separates a dialog is its outline, and the
outline is therefore `--control-border` — the token already reserved for "the boundary of anything
a person operates" — measured at 4.27:1 against the scrimmed page and 3.15:1 against the dialog's
own fill, visible from both sides for the reason a field's border is.

The scrim's job is the other one: it says the page behind is not operable. That claim needs no
ratio, which is why it is stated here rather than measured.

This is a correction to Layout's "a layer that floats is separated by `--surface-2` and a
`--border-strong` outline, and that is the whole mechanism". That holds for a select's list and a
menu, which sit inside the flow and are read against the control that opened them. It does not
hold for a modal over a full-width table, and `--border-strong` at 1.88:1 against a scrimmed page
is the number that says so.

**A destructive confirm takes `--accent-fill`, not a red fill.** There is no bright red surface in
this file, and `--danger-text` as a fill would put pale text on `#F0837E`. The danger role appears
in a dialog the way it appears everywhere else — as an inline notice above the action row, saying
what will happen with the real date in it. A sentence that reads *Access runs to 09 Sep 2026 and
then stops* is more specific than any colour, and inventing a red fill for one control would be a
value this file does not have.

**The dismissing action is never labelled `Cancel`** on a dialog that cancels a subscription. Both
buttons would name the same word for opposite actions. It is `Keep subscription`, and the pattern
generalises: the dismissing action names what stays true.

## Links

A link is `--accent-text`, no underline at rest, underlined on hover and on focus. It is the only
accent-coloured text in a table row, which is what makes it findable without a decoration.

Table furniture that happens to be clickable is not a link: a sortable column header stays
`--text-secondary` and shows its affordance by changing to `--text-primary` on hover. A header
that turned blue would claim to navigate somewhere.

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

## Charts

Five figures, one question each. Every number on one of them has an event `substate` actually
emitted behind it, which is the rule that decides what may be drawn at all.

**A figure is a panel, not a picture.** It carries the question as its heading and the answer as
one number, and the plot is the working underneath both. A reader who takes only the heading and
the number has got the point.

| Part | Value |
|---|---|
| fill | `--surface-1` |
| radius | `8px`, the step Radius already assigns to a chart frame |
| padding | `16px` |
| heading | `16px`, `--text-primary` — the question, not the metric's name |
| the answer | `20px`, mono, `--text-primary` |
| caption under the heading | `12px`, `--text-muted` |
| heading block to plot | `12px` |
| plot | `--chart-plot`, `224px` |
| between figures | `16px`, as between cards |

`224px` is derived rather than chosen, from the busiest of the five. The states snapshot has five
bars; five at the table's own `40px` row height come to `200px`, and the remaining `24px` is
`4px` of gap in each of the six places there is one — between each pair and above and below.

**A bar is never thicker than a table row.** A figure with three marks does not grow its bars to
fill the plot: three slabs are a different chart from five bars, and the reader would be told that
the two figures are measuring different things when they are not.

Layout says a control's height is not a number, and this does not contradict it. A control's
height follows its type and its padding; a plot has no type to follow, so the height is a value,
and a value belongs in this file rather than in a component.

### Colour

**A series takes a colour from this file or it is not drawn.** Chart.js paints to a canvas, so it
takes colours as JavaScript values rather than as utilities — which is why neither the one-palette
grep nor `scripts/utilities.py` can see them. That gap is closed by a check of its own: a hex,
`rgb()`, `hsl()` or `oklch()` literal anywhere in the chart sources fails the build, and every
token the chart palette names has to exist in `tokens.css`.

| Figure | Series | Colour |
|---|---|---|
| Funnel | one, three stages | `--accent-text` |
| Inflow and outflow | joined | `--success-text` |
| | left | `--danger-text`, dashed |
| States now | five, one per state | the five state chips' **text** colours |
| Revenue | one | `--accent-text` |
| Quiet, by how long | one, three buckets | `--accent-text` |

**A single-series figure is accent, and a screen carrying one has no filled accent control.**
Accent's one-filled-element rule is about actions: it makes the important action findable, and it
stops working when there are two. A bar is not an action, so it spends nothing — as long as the
screen it is on has no filled button to compete with. Analytics has none, which is correct for a
screen with nothing to press.

**The states figure takes the chips' text colours, not their fills.** A chip's fill is a tint
drawn behind `12px` of text; as a bar on a panel it reads 1.15:1 to 1.31:1 and is not there. The
text colours are the ones a reader of the table has already learnt, and each is measured against
the frame: `TRIAL` 8.63, `ACTIVE` 9.41, `GRACE` 9.55, `EXPIRED` 5.72, `CANCELLED` 7.12 — all past
the 3:1 that 1.4.11 asks of anything you have to see to read the figure.

**The two lines differ by more than hue.** `--success-text` and `--danger-text` are 1.47:1 apart,
which is a difference of hue and of nothing else, so the outflow line is dashed as well as red.
A reader who cannot separate the two hues still has two lines.

**Outflow is danger, not the `CANCELLED` rose.** A line here is a direction, not a state, and the
semantic roles are the tokens this file keeps for direction — the same reason success and warning
share their colours with `ACTIVE` and `GRACE`. The rose stays where it means one state.

**The states figure is ordered by urgency, not by lifecycle**, because the backend already fixed
that order for the table and a second order invented here would be the second dictionary this
project has twice refused: `GRACE`, `TRIAL`, `ACTIVE`, `CANCELLED`, `EXPIRED`.

### Furniture

| Part | Value |
|---|---|
| grid lines along the value axis | `--border`, `1px` |
| grid lines along the category axis | none |
| axis rule | none; the grid line at zero is the axis |
| tick labels | `12px`, mono, `--text-muted` |
| legend | `12px`, `--text-secondary`, above the plot, left, only where there are two series |
| bar and line fill | the series colour at full strength; no gradient |

Ticks are mono for the reason Typography gives: they are numbers compared down a column, and
proportional digits make two of the same length look different lengths.

**A tooltip is a floating layer** and takes what Layout gives one — `--surface-2` with a
`--border-strong` outline, `6px` radius, `13px`, `--text-primary`. No shadow, here as everywhere.

**A figure animates once and then holds still.** `200ms` on first paint, the ceiling Floor sets
for a transition, and nothing on an update: a figure that replayed itself whenever its data
arrived would tell the whole story again every time a poll came back. Under
`prefers-reduced-motion` the duration is `0` and the figure is simply there.

### The caption names where the number came from

Two sources sit behind these five figures and they answer different questions. The engine holds
what is true now; the journal holds what happened. A reader who takes "expired" off one figure and
off the subscriber table gets `46` from one and `360` from the other, and both are correct.

So **every figure's caption names its source in the reader's words**, under the heading, at
`12px` in `--text-muted`: *standing now* against *movements in the period*. It is one line, it is
where the number is being read, and it is the only place that difference can honestly be put —
a reader comparing two screens is not holding a document open beside them.

The one figure that must agree with the table exactly is the states snapshot, because it asks the
table's own question of the table's own source.

### The four states of a figure

Loading is the frame with a skeleton in the plot's place at `--chart-plot`, and a bar where the
heading will be — the shape of what is coming, per Loading. Empty says what would put something
there. Error names what failed and offers the retry beside it.

**A world that has not been built says so once, for the screen, not five times.** Every figure
reads the same world and would meet the same emptiness, so the refusal replaces the figures rather
than appearing inside each of them. That is the component the subscriber table already uses.

### What a figure never does

- **No second value axis.** Two scales on one plot let any two lines cross wherever the author
  would like them to.
- **No pie.** The snapshot is the one figure that invites it, and five angles are harder to
  compare than five lengths — which is the entire job of that figure.
- **No axis that does not start at zero.** A truncated one exaggerates every difference drawn
  against it, and does so silently.

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

### Time

**A moment is absolute unless the question is "recently or not".**

The event feed and the audit print the instant: `09 Sep 2026 14:07`, mono, UTC. They are read
against the boundaries on the card — did the payment arrive before the period ended — and
`3 months ago` next to `09 Sep 2026` makes the reader do the arithmetic to find out whether the
two agree.

**They carry the time and a boundary does not**, which is the same rule applied twice: a feed and
an audit are read for *when*, and two operations a minute apart are two rows somebody has to tell
apart. A boundary at 14:07 is a fact about a clock rather than about the subscription, and
printing it invites a comparison of minutes that mean nothing.

Last activity is the exception and keeps `9 days ago` — in the table's column and on the card
alike, because it is the same question in both places: has this person been seen lately. A date
there makes the reader do the subtraction. The rule is the question, not the screen: relative
where the answer is a duration, absolute where the answer is an instant that will be compared with
another one.

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

**A skeleton is the shape of what is coming, per block.** Three shapes exist, and each is the
outline of the thing it stands in for rather than a rectangle:

| Block | Skeleton |
|---|---|
| a card | the card's frame, with one bar per row it will have at the row's height |
| a feed | four rows at the feed row's height, inside the feed's own frame |
| a table | five rows at the table row's height, inside the table's frame |

The count is fixed and deliberately short of a full page: a skeleton the height of twenty-five
rows is a page that shortens when the data arrives, which is the jump the skeleton exists to
prevent in the other direction.

An **empty** feed and an empty audit say what would put something there, not that there is
nothing — the same rule the subscriber table follows. An **error** names what failed and offers
the retry beside it, because the usual cause is the network and the usual fix is asking again.

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

**Three things this interface decided not to have.** An absence is a decision like any other, and
an unrecorded one gets re-decided by whoever needs it next:

- **No toast.** A result appears where the action was taken — an inline notice inside the panel
  that owns the button — and stays until the next action. A toast needs a dwell time this file
  does not have, and it disappears while the person is reading the thing it changed.
- **No colour on an event type.** The thirteen types in the feed are neutral fact labels. Green
  and amber already mean `ACTIVE` and `GRACE`; a `payment.recorded` row tinted green would spend
  a subscription state's colour on something that is not a state.
- **No date control.** Nothing here filters by a date range, because there is no date input in
  this interface and no recipe for one in this file. A filter nobody can operate is not a filter,
  and inventing the control at the first screen that wants it is how a design file stops being
  where values come from.

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
| a dialog's edge is measured against what is behind it | `scripts/contrast.py` composites `--scrim` over both surfaces and measures the outline on the result |
| a colour reaches a canvas from this file | `scripts/colours.py` fails on a colour literal in the frontend sources, and on a token name the stylesheet does not declare |

**Nobody checks these but a person.** They are the rules worth reading the diff for.

- at most one filled accent element per screen
- an input sits inside a `--surface-1` container or higher
- disabled is for an action that is unavailable, never for one in progress
- buttons named for what happens, sentence case throughout
- text dimmed with a token, never with `opacity`
- a skeleton in the shape of what is coming, not a spinner
- a figure's caption names whether its number is standing now or a movement in the period

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

**A canvas is outside all of it, which is why there is a check of its own.** A chart library is
handed colours as JavaScript values, so a hex written into a chart config is not a utility, does
not touch a cleared namespace, and is not a `--color-*` definition in a stylesheet — it passes
every guard above while being exactly the second palette they exist to prevent. `scripts/colours.py`
reads the sources instead, with comments removed for the reason `utilities.py` gives, and asks two
questions: is there a colour literal here, and does every token named here exist. The second is
the one that matters — a token that does not exist resolves to the empty string, which draws
nothing and says nothing, and the source still reads correctly.

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
  | a dialog's outline on the scrimmed page | 4.27 | 3.0 |
  | a dialog's outline on a scrimmed panel | 4.16 | 3.0 |
  | `--surface-2` on the scrimmed page | 1.36 | exempt: the outline identifies the dialog, not the fill |
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
