"""Every colour a component draws with, and whether the palette is where it came from.

Tailwind's `--color-*` namespace is cleared, so a utility asking for a colour this project does
not have compiles to nothing and `utilities.py` says so.

A canvas takes no utilities. Chart.js is handed colours as JavaScript values, so every rule that
keeps docs/design.md the one place a colour is written reaches that code through nothing at all.

Two questions, and the second is the half that matters:

    is there a colour literal here          a hex, a colour function, a CSS colour keyword
    does every token named here exist       `--color-accent-text` has to be in tokens.css

A token that does not exist resolves to the empty string, which a canvas draws as nothing. The
first question alone would pass that, and the plot would come up blank with the source reading
correctly.

Comments come out first: `AppButton.vue` explains its own no-colour-prop rule with two hexes in
the sentence, and a check that makes somebody reword that is one they reword the rule to escape.

Run through ./scripts/check-design.sh, which owns the tokens file this reads.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "frontend" / "src"
TOKENS = SOURCE / "styles" / "tokens.css"

_COMMENTS = (
    re.compile(r"<!--.*?-->", re.S),
    re.compile(r"/\*.*?\*/", re.S),
    re.compile(r"(?<![:\w])//[^\n]*"),
)

# A hex or a colour function cannot be ordinary prose, so these are looked for in the whole file.
_LITERAL_COLOUR = re.compile(
    r"#[0-9a-fA-F]{3,8}\b|\b(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\s*\(",
)

# A bare word can be prose, so these are looked for only inside a string in a script.
_KEYWORDS = frozenset(
    {
        "white",
        "black",
        "red",
        "green",
        "blue",
        "grey",
        "gray",
        "silver",
        "orange",
        "yellow",
        "purple",
        "pink",
        "navy",
        "teal",
        "aqua",
        "lime",
        "maroon",
        "olive",
        "fuchsia",
    }
)

_SCRIPT = re.compile(r"<script\b[^>]*>(?P<body>.*?)</script>", re.S)
_STRING = re.compile(r"""(['"`])(?P<body>(?:\\.|(?!\1).)*)\1""", re.S)

# Any custom property the source names. The theme's own namespaces only: a component is free to
# invent `--reka-height`, which is a vendor's variable and not a value this project decides.
_TOKEN = re.compile(r"--(?:color|spacing|radius|text|container|font)-[a-z0-9-]+")


def without_comments(text: str) -> str:
    for pattern in _COMMENTS:
        text = pattern.sub(" ", text)
    return text


def scripts_of(text: str, *, single_file_unit: bool) -> list[str]:
    """The TypeScript in a file. In a `.vue` that is its `<script>` blocks; elsewhere, all of it."""
    if not single_file_unit:
        return [text]
    return [block.group("body") for block in _SCRIPT.finditer(text)]


def declared() -> set[str]:
    """Every custom property `tokens.css` defines, aliases included."""
    body = TOKENS.read_text(encoding="utf-8")
    found = {name for name in _TOKEN.findall(body) if f"{name}:" in body}
    if not found:
        raise SystemExit(f"no --color-* declarations in {TOKENS}; there is nothing to check against")
    return found


def offences(path: Path, text: str) -> list[str]:
    body = without_comments(text)
    single_file_unit = path.suffix == ".vue"
    found = []

    for match in _LITERAL_COLOUR.finditer(body):
        found.append(f"the colour literal {match.group(0)!r}")

    for script in scripts_of(body, single_file_unit=single_file_unit):
        for literal in _STRING.finditer(script):
            for word in re.split(r"[^a-z]+", literal.group("body").lower()):
                if word in _KEYWORDS:
                    found.append(f"the colour keyword {word!r}")

    return found


def main(argv: list[str]) -> int:
    known = declared()
    failures = 0

    for path in sorted(SOURCE.rglob("*")):
        if path.suffix not in {".vue", ".ts"} or path.name.endswith(".spec.ts"):
            continue
        text = path.read_text(encoding="utf-8")
        where = path.relative_to(ROOT)

        for offence in offences(path, text):
            print(
                f"::error file={where}::{offence} is a second palette; "
                "a colour comes from a token in docs/design.md or it is not drawn"
            )
            failures += 1

        for token in sorted(set(_TOKEN.findall(without_comments(text)))):
            if token not in known:
                print(
                    f"::error file={where}::{token} is not declared in "
                    f"{TOKENS.relative_to(ROOT)}; it resolves to the empty string, which draws "
                    "nothing and says nothing"
                )
                failures += 1

    if failures:
        return 1
    print(f"    ok    every colour in the frontend comes from one of {len(known)} declared tokens")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
