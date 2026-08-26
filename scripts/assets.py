"""Everything the built stylesheet loads, and whether it comes from this origin.

WHY THIS EXISTS. `shadcn-vue`'s generator writes an `@import` for Inter from `fonts.googleapis.com`
into the stylesheet it is pointed at. It has done so twice now — once at `init` and once at the
first `add` afterwards — and it will do so again, because it is not a mistake on its part but what
it is written to do.

The failure that follows is silent in every direction. The panel's Content-Security-Policy is
`default-src 'self'` with no `font-src`, so the browser refuses the request; the page renders in
the fallback stack and nothing breaks; and the check that counts `@font-face` rules stays green,
because it counts the four rules the bundled faces produce and a remote `@import` contributes
none. Nobody finds out except by looking at the typography and already knowing what it should be.

So the rule is the simple one: everything the stylesheet loads has to be next to it. A relative or
root-relative path is bundled and served from this origin; a `data:` URI carries its own bytes.
Anything with a scheme, and anything protocol-relative, is a request to somebody else's machine.

WHY IT PARSES. The grep for this would be `grep -E "https?:|//"`, which matches the `//` in every
source map comment and every `url(//` that is not there. The parser strips comments and strings
first and then looks only where a URL can actually be: the argument of `url()` and the target of
`@import`.

Run through ./scripts/check-design.sh, which owns the build it reads.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# `url( … )` with an optional quote, and `@import` in both of its forms — `@import "x"` and
# `@import url(x)`, each of which may be followed by a media query this does not care about.
_URL = re.compile(r"""url\(\s*(?P<q>["']?)(?P<target>[^"')]+)(?P=q)\s*\)""", re.I)
_IMPORT = re.compile(r"""@import\s+(?!url\()(?P<q>["'])(?P<target>[^"']+)(?P=q)""", re.I)

# A comment can contain anything, including the sourceMappingURL that ends most built files.
_COMMENT = re.compile(r"/\*.*?\*/", re.S)

_SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.I)


def targets(css: str) -> list[str]:
    """Every URL the stylesheet asks the browser to fetch, in the order they appear."""
    body = _COMMENT.sub(" ", css)
    found: list[tuple[int, str]] = []
    for pattern in (_URL, _IMPORT):
        for match in pattern.finditer(body):
            found.append((match.start(), match.group("target").strip()))
    return [target for _, target in sorted(found) if target]


def is_foreign(target: str) -> bool:
    """Whether fetching this reaches beyond the origin serving the page.

    `data:` carries its own bytes and reaches nowhere. Everything else with a scheme, and the
    protocol-relative `//host/path`, is somebody else's machine.
    """
    if target.startswith("//"):
        return True
    scheme = _SCHEME.match(target)
    if scheme is None:
        return False
    return scheme.group(0).lower() != "data:"


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: assets.py <built.css>", file=sys.stderr)
        return 2

    path = Path(argv[0])
    foreign = [target for target in targets(path.read_text(encoding="utf-8")) if is_foreign(target)]

    for target in foreign:
        print(
            f"::error file=frontend/src/styles/tokens.css::the built stylesheet loads "
            f"{target[:120]} from another origin. The panel's CSP refuses it, the page renders on "
            f"the fallback and nothing else notices — everything it loads has to be bundled"
        )
    return 1 if foreign else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
