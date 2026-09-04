"""Measure every colour pair in docs/design.md and say which ones hold.

WCAG 2.1 relative luminance and contrast ratio. Thresholds used here:
  4.5:1  normal text (everything in this interface: the largest size is 20px, and WCAG's "large"
         starts at 24px, so no text here qualifies for the lower bar)
  3.0:1  1.4.11, non-text contrast: the boundary of a control, and anything a person must see to
         know a component is there
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Final


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    parts = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    linear = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def ratio(a: str, b: str) -> float:
    la, lb = luminance(a), luminance(b)
    lighter, darker = max(la, lb), min(la, lb)
    return (lighter + 0.05) / (darker + 0.05)


TOKENS: Final = Path(__file__).resolve().parent.parent / "frontend/src/styles/tokens.css"
HEX: Final = re.compile(r"--color-([a-z0-9-]+):\s*(#[0-9a-fA-F]{6})\b")


def palette() -> dict[str, str]:
    """The colours as the stylesheet declares them, not a copy of them.

    A hard-coded table is a second palette: it went on reporting the ratios of colours the panel
    had stopped using, and a value edited in `tokens.css` alone was measured by nothing.
    """
    found = dict(HEX.findall(TOKENS.read_text(encoding="utf-8")))
    if not found:
        raise SystemExit(f"no --color-*: #rrggbb in {TOKENS}; there is nothing to measure")
    return found


T = palette()

# --scrim is rgba(0,0,0,0.55) and cannot be measured as a hex, so what is measured is what a reader
# actually sees: the surface with the scrim composited over it. Written out rather than computed
# from an alpha here, because these two values are what docs/design.md quotes.
T["scrim-over-surface-0"] = "#080B0E"
T["scrim-over-surface-1"] = "#0B0F13"

# (foreground, background, threshold, applies, what it is)
#
# `applies` is the honest half. WCAG 1.4.11 covers what is REQUIRED TO IDENTIFY a component or its
# state — not every pair of colours that happen to touch. A state chip is identified by its text,
# which is measured separately and passes comfortably; its tinted background is reinforcement, and
# holding it to 3:1 would mean five chips the colour of the page. Pairs like that are measured and
# printed anyway, because a number nobody wrote down is a number nobody can argue with later, but
# they are not failures.
PAIRS: list[tuple[str, str, float, bool, str]] = []

for surface in ("surface-0", "surface-1", "surface-2"):
    for text in ("text-primary", "text-secondary", "text-muted"):
        PAIRS.append((text, surface, 4.5, True, "body text"))
    PAIRS.append(("accent-text", surface, 4.5, True, "link, active icon"))

PAIRS += [
    ("on-accent", "accent-fill", 4.5, True, "text on the filled button"),
    ("on-accent", "accent-fill-hover", 4.5, True, "text on the filled button, hover"),
    ("text-primary", "accent-bg", 4.5, True, "text on a selected row"),

    ("control-border", "surface-0", 3.0, True, "input outline against its own fill"),
    ("control-border", "surface-1", 3.0, True, "input outline against the panel around it"),
    ("control-border", "surface-2", 3.0, True, "control outline inside a dialog"),

    ("accent-text", "surface-1", 3.0, True, "focus ring as a boundary"),
    ("accent-text", "surface-0", 3.0, True, "focus ring on the page"),

    # The placeholder is not a component and identifies nothing; it is motion that says "pending".
    # Measured because the reduced-motion path removes the motion, which is why that path carries
    # an outline in --control-border instead.
    ("skeleton-base", "surface-1", 3.0, False, "skeleton on a panel — carried by motion, or by its outline"),
    ("skeleton-highlight", "surface-1", 3.0, False, "skeleton at the top of its pulse"),
    # Deliberately not required, and this is the note that stops it being "restored" as an
    # oversight: the outline exists to separate the placeholder from the PANEL, and that pair —
    # control-border on surface-1 — is required above and passes. Against the skeleton's own fill
    # it is a slightly lighter edge, which is what an outline looks like. Requiring 3:1 here would
    # be measuring the wrong side of the line.
    ("control-border", "skeleton-base", 3.0, False, "reduced-motion outline, inner edge"),

    # 1.4.11 exempts inactive components in as many words.
    ("text-disabled", "fill-disabled", 4.5, False, "label of a disabled control — exempt, measured anyway"),

    ("border", "surface-1", 3.0, False, "hairline between rows — decoration, not identification"),
    ("border-strong", "surface-1", 3.0, False, "optional underline, hover — no longer load-bearing"),
]

for role in ("trial", "active", "grace", "expired", "cancelled"):
    PAIRS.append((f"state-{role}-text", f"state-{role}-bg", 4.5, True, f"{role} chip text"))
    PAIRS.append((f"state-{role}-bg", "surface-1", 3.0, False, f"{role} chip fill — the text identifies it"))

# A chart series IS what identifies its own mark: a bar with no colour is not a shorter bar, it is
# a bar the reader cannot attribute. So 1.4.11 applies to it in a way it does not apply to a chip's
# fill, and these are required rather than merely measured.
for role in ("trial", "active", "grace", "expired", "cancelled"):
    PAIRS.append((f"state-{role}-text", "surface-1", 3.0, True, f"{role} bar in the states figure"))

PAIRS += [
    ("accent-text", "surface-1", 3.0, True, "a single-series bar or line"),
    ("success-text", "surface-1", 3.0, True, "the inflow line"),
    ("danger-text", "surface-1", 3.0, True, "the outflow line"),
    # The two lines are 1.47:1 apart, which is hue and nothing else — so the outflow line is
    # dashed as well as red, and this number is why that dash is not decoration.
    ("success-text", "danger-text", 3.0, False, "inflow against outflow — separated by the dash, not by this"),
    ("border", "surface-1", 3.0, False, "a chart's grid line — the ticks label the scale, not this"),
]

for role in ("success", "warning", "danger"):
    PAIRS.append((f"{role}-text", f"{role}-bg", 4.5, True, f"{role} notice text"))
    PAIRS.append((f"{role}-bg", "surface-1", 3.0, False, f"{role} notice fill against a panel"))
    PAIRS.append((f"{role}-border", f"{role}-bg", 3.0, False, f"{role} notice border — edging, not the notice"))

PAIRS += [
    # A dialog. Its edge is the outline and not the fill, because no scrim on this palette can
    # buy the fill a 3:1 edge — measured below, and the reason is in docs/design.md.
    ("control-border", "scrim-over-surface-0", 3.0, True, "dialog outline against the scrimmed page"),
    ("control-border", "scrim-over-surface-1", 3.0, True, "dialog outline against a scrimmed panel"),
    ("surface-2", "scrim-over-surface-0", 3.0, False, "dialog fill — the outline identifies it"),
    ("text-secondary", "surface-2", 4.5, True, "permission chip text"),
    ("surface-2", "surface-1", 3.0, False, "permission chip fill — the text identifies it"),
]

# Pairs that are short, named one by one, with the number they were short by when they were
# written down. This is a waiver, not a silence: the run prints them every time, a pair that is not
# on this list fails the build, and a pair that IS on it fails the build as soon as it gets worse.
# The list cannot grow without someone editing this file and saying why.
#
# All three are the same cause. --surface-2 is lighter than --surface-1, so anything drawn on it
# loses contrast, and the palette was checked against --surface-0 and --surface-1 only. Nothing
# sits on --surface-2 today but the permission chip, whose text is 7.19:1 — so nothing is wrong on
# screen right now. Dialogs, popovers and dropdowns are what --surface-2 is for, and muted text,
# links and control outlines will all land there. Lifting the three tokens is a palette decision.
KNOWN_SHORT: dict[tuple[str, str], float] = {
    # Empty, and the mechanism stays. A waiver here names one pair, records the ratio it had when
    # it was written down, and is printed on every run: a pair that is not on this list fails the
    # build, and a pair that IS on it fails as soon as it gets worse. That is the difference
    # between a known gap and a silence, and it is worth keeping wired up for the next time the
    # palette moves ahead of the screens.
    #
    # It last held the three pairs on --surface-2, which were short because the palette had been
    # checked against --surface-0 and --surface-1 and never against the surface above them. They
    # were fixed by lifting the three tokens rather than by darkening --surface-2: at the value
    # that cleared 4.5:1 the raised surface sat 1.02:1 from --surface-1, so a dialog stopped
    # reading as raised and the three-surface system stopped meaning anything.
}

failures: list[str] = []
waived: list[str] = []
print(f"{'pair':<44}{'ratio':>7}{'need':>7}  {'verdict':<9} what")
print("-" * 112)
for fg, bg, need, applies, what in PAIRS:
    r = ratio(T[fg], T[bg])
    if not applies:
        verdict = "measured"
    elif r >= need:
        verdict = "ok"
    elif (fg, bg) in KNOWN_SHORT:
        recorded = KNOWN_SHORT[(fg, bg)]
        if r < recorded - 0.005:
            verdict = "WORSE"
            failures.append(
                f"{fg} on {bg}: {r:.2f}, was {recorded:.2f} when it was waived — it got worse"
            )
        else:
            verdict = "waived"
            waived.append(f"{fg} on {bg}: {r:.2f}, needs {need:.1f} — {what}")
    else:
        verdict = "SHORT"
        failures.append(f"{fg} on {bg}: {r:.2f}, needs {need:.1f} — {what}")
    print(f"{fg + ' on ' + bg:<44}{r:>7.2f}{need:>7.1f}  {verdict:<9} {what}")

print()
if waived:
    print(f"{len(waived)} known-short pair(s), waived and awaiting a palette decision:")
    for w in waived:
        print("  " + w)
    print()
if failures:
    print(f"{len(failures)} pair(s) below the requirement:")
    for f in failures:
        print("  " + f)
else:
    print("every pair the requirement applies to holds")
sys.exit(1 if failures else 0)
