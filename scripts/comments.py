"""Consecutive comment lines, counted by parsing rather than by matching.

Decision 166 put a ceiling on a comment; this is what makes it hold. Everything below answers one
question per line — is this line entirely prose — and the whole difficulty is that `#` and `//`
are ordinary characters inside a string, a regex, a shell expansion, an attribute and a URL.

Run it:  python3 scripts/comments.py            judge the tree
         python3 scripts/comments.py --measure  the survey the ceiling was chosen against
         python3 scripts/comments.py --update   re-record scripts/comment-debt.txt
"""

from __future__ import annotations

import ast
import io
import re
import subprocess
import sys
import tokenize
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Final

CEILING: Final = 3
"""Three lines, from decision 166. A fourth is the refusal."""

MARKER: Final = re.compile(
    r"^\s*(?:#+|//+|/?\*+|<!--)?\s*LONG BECAUSE:\s*(?P<reason>.+?)\s*(?:-->|\*/)?$"
)
"""The one way past the ceiling, written as the block's own first line.

The comment character is stripped before the match because every language this reads writes its
comments with one, and a marker that only worked in a Python docstring would be no marker at all.
"""

REASON_WORDS: Final = 5
"""A clause, not a word. `LONG BECAUSE: legacy` is the shape this number exists to refuse."""

DELIMITER: Final = re.compile(r"""^(?:[rRbBuUfF]{0,2}(?:"{3}|'{3})|/\*\*?|\*/|<!--|-->)$""")
"""A line carrying no prose. The closing `\"\"\"` of a docstring and the `*/` of a JSDoc block are
syntax, and counting them would make a three-line paragraph measure five. Only discounted at the
edge of a block, so a `/*` written inside one cannot be used to saw a wall in half."""


def lines_of(text: str) -> list[str]:
    """Split on `\\n` alone.

    `str.splitlines` also breaks on a form feed and on U+2028, which Python's tokenizer does not.
    A file holding either would have two line numberings, and the comment spans would land on the
    wrong one.
    """
    return text.split("\n")


def line_offsets(text: str) -> list[int]:
    offsets, position = [], 0
    for line in lines_of(text):
        offsets.append(position)
        position += len(line) + 1
    return offsets


@dataclass(frozen=True, slots=True)
class Marks:
    comment: set[int]
    documentation: set[int]

    @staticmethod
    def empty() -> Marks:
        return Marks(set(), set())


def _span(marks: set[int], start: int, end: int) -> None:
    marks.update(range(start, end))


# --------------------------------------------------------------------------------------------
# Python. `tokenize` for the comments, `ast` for the prose; both are the language's own reader.
# --------------------------------------------------------------------------------------------


def _character_column(line: str, byte_column: int) -> int:
    """`ast` counts columns in UTF-8 bytes and everything else here counts characters.

    An em dash is three bytes, so a docstring ending in one used to run three characters past its
    own quotes and swallow the code beneath it.
    """
    return len(line.encode("utf-8")[:byte_column].decode("utf-8", "ignore"))


def scan_python(text: str) -> Marks:
    comment: set[int] = set()
    documentation: set[int] = set()
    offsets = line_offsets(text)
    lines = lines_of(text)

    for token in tokenize.generate_tokens(io.StringIO(text).readline):
        if token.type == tokenize.COMMENT:
            start = offsets[token.start[0] - 1] + token.start[1]
            _span(comment, start, offsets[token.end[0] - 1] + token.end[1])

    # A string standing alone as a statement: module, class and function docstrings, and the ones
    # this project writes under an attribute. Nothing else has that shape.
    for node in ast.walk(ast.parse(text)):
        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Constant):
            continue
        if not isinstance(node.value.value, str) or node.end_lineno is None:
            continue
        start = offsets[node.lineno - 1] + _character_column(lines[node.lineno - 1], node.col_offset)
        end = offsets[node.end_lineno - 1] + _character_column(
            lines[node.end_lineno - 1], node.end_col_offset
        )
        _span(documentation, start, end)

    return Marks(comment, documentation)


# --------------------------------------------------------------------------------------------
# JavaScript and TypeScript. A regex may hold every other opener, which is why this scans.
# --------------------------------------------------------------------------------------------

BEFORE_REGEX: Final = frozenset("(,=:[!&|?{};+-*%~^<>")
KEYWORD_BEFORE_REGEX: Final = frozenset(
    {
        "return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
        "case", "do", "else", "throw", "yield", "await",
    }
)


def scan_javascript(text: str, base: int = 0) -> Marks:
    comment: set[int] = set()
    _javascript(text, base, comment, 0, len(text))
    return Marks(comment, set())


def _javascript(text: str, base: int, comment: set[int], index: int, stop: int, *,
                until_brace: bool = False) -> int:
    """Scans to `stop`, or to the `}` that closes an interpolation. Returns where it stopped."""
    previous = ""
    depth = 0

    while index < stop:
        char = text[index]

        if char == "/" and index + 1 < stop and text[index + 1] == "/":
            end = text.find("\n", index, stop)
            end = stop if end == -1 else end
            _span(comment, base + index, base + end)
            index = end
            continue

        if char == "/" and index + 1 < stop and text[index + 1] == "*":
            end = text.find("*/", index + 2, stop)
            end = stop if end == -1 else end + 2
            _span(comment, base + index, base + end)
            index = end
            continue

        if char in "'\"":
            index = _quoted(text, index, char, stop)
            previous = char
            continue

        if char == "`":
            index = _template(text, base, comment, index, stop)
            previous = char
            continue

        if char == "/" and _regex_may_start(text, index, previous):
            index = _regex(text, index, stop)
            previous = "/"
            continue

        if until_brace:
            if char == "{":
                depth += 1
            elif char == "}":
                if depth == 0:
                    return index + 1
                depth -= 1

        if not char.isspace():
            previous = char
        index += 1

    return index


def _quoted(text: str, index: int, quote: str, stop: int) -> int:
    index += 1
    while index < stop:
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == quote:
            return index + 1
        # An unterminated quote is a syntax error, not a string that eats the rest of the file.
        if text[index] == "\n":
            return index
        index += 1
    return index


def _template(text: str, base: int, comment: set[int], index: int, stop: int) -> int:
    index += 1
    while index < stop:
        if text[index] == "\\":
            index += 2
            continue
        if text[index] == "`":
            return index + 1
        if text.startswith("${", index):
            index = _javascript(text, base, comment, index + 2, stop, until_brace=True)
            continue
        index += 1
    return index


def _regex(text: str, index: int, stop: int) -> int:
    index += 1
    inside_class = False
    while index < stop:
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "\n":
            return index
        if char == "[":
            inside_class = True
        elif char == "]":
            inside_class = False
        elif char == "/" and not inside_class:
            return index + 1
        index += 1
    return index


def _regex_may_start(text: str, index: int, previous: str) -> bool:
    if previous == "" or previous in BEFORE_REGEX:
        return True
    if not (previous.isalnum() or previous in "_$)]"):
        return True
    # `return /x/` divides nothing: the character before the slash is a letter either way, so it
    # is the word that ends there that decides.
    word = re.search(r"([A-Za-z_$][\w$]*)\s*$", text[:index])
    return word is not None and word.group(1) in KEYWORD_BEFORE_REGEX


# --------------------------------------------------------------------------------------------
# Shell. `#` opens a comment only at the start of a word, and `<<` is a heredoc only sometimes.
# --------------------------------------------------------------------------------------------

HEREDOC: Final = re.compile(r"<<(?P<dash>-?)\s*(?P<quote>['\"]?)\\?(?P<word>[A-Za-z_][\w]*)(?P=quote)")


def scan_shell(text: str) -> Marks:
    comment: set[int] = set()
    index, stop = 0, len(text)
    at_word_start = True
    pending: list[tuple[str, bool]] = []
    arithmetic = 0

    while index < stop:
        char = text[index]

        if char == "\n":
            index += 1
            while pending:
                word, indented = pending.pop(0)
                index = _skip_heredoc(text, index, word, indented)
            at_word_start = True
            continue

        if char == "\\":
            # A continued line starts a new word, so a comment may open on it.
            at_word_start = text[index + 1 : index + 2] == "\n"
            index += 2
            continue

        if char in "'\"":
            index = _shell_quoted(text, index, char)
            at_word_start = False
            continue

        if text.startswith("$((", index):
            arithmetic += 1
            index += 3
            at_word_start = False
            continue
        if arithmetic and text.startswith("))", index):
            arithmetic -= 1
            index += 2
            at_word_start = False
            continue

        # `<<<` is a here-string and `1 << n` inside `$(( ))` is a shift. Neither opens a heredoc.
        if (
            text.startswith("<<", index)
            and not text.startswith("<<<", index)
            and text[index - 1 : index] != "<"
            and not arithmetic
        ):
            found = HEREDOC.match(text, index)
            if found is not None:
                pending.append((found.group("word"), found.group("dash") == "-"))
                index = found.end()
                at_word_start = False
                continue

        if char == "#" and at_word_start:
            end = text.find("\n", index)
            end = stop if end == -1 else end
            _span(comment, index, end)
            index = end
            continue

        at_word_start = char.isspace() or char in ";|&("
        index += 1

    return Marks(comment, set())


def _shell_quoted(text: str, index: int, quote: str) -> int:
    # `$'...'` takes backslash escapes; a plain '...' does not, and a backslash in it is literal.
    escapes = quote == '"' or text[index - 1 : index] == "$"
    index += 1
    while index < len(text):
        if escapes and text[index] == "\\":
            index += 2
            continue
        if quote == '"' and text.startswith("$(", index):
            index = _substitution(text, index + 2)
            continue
        if text[index] == quote:
            return index + 1
        index += 1
    return index


def _substitution(text: str, index: int) -> int:
    """`$( … )` inside a double-quoted string is shell again, and its quotes are its own.

    Without this the outer string closes on the first nested `"`, and every quote after it pairs
    with the wrong partner — which is how a string came to straddle a newline and swallow the
    comments below it. This is the parity flip that has bitten this repository twice.
    """
    depth = 1
    while index < len(text):
        char = text[index]
        if char in "'\"":
            index = _shell_quoted(text, index, char)
            continue
        if text.startswith("$(", index):
            depth += 1
            index += 2
            continue
        if char == ")":
            depth -= 1
            index += 1
            if depth == 0:
                return index
            continue
        index += 1
    return index


def _skip_heredoc(text: str, index: int, word: str, indented: bool) -> int:
    """Past the terminator line. The body is data — a `#` in it opens nothing.

    Only `<<-` allows the terminator to be indented; matching a stripped line for a plain heredoc
    ends the body early and bills the rest of the data as comment.
    """
    while index < len(text):
        cut = text.find("\n", index)
        cut = len(text) if cut == -1 else cut
        line = text[index:cut]
        if (line.strip() if indented else line) == word:
            return cut
        index = cut + 1
    return len(text)


# --------------------------------------------------------------------------------------------
# YAML, and the shell inside a `run:` block.
# --------------------------------------------------------------------------------------------

BLOCK_LINE: Final = re.compile(
    r"""^(?P<indent>\s*)(?:-\s+)?(?:(?P<key>[^#:'"]*?)\s*:)?\s*"""
    r"""(?:[&*!]\S+\s+)*[|>](?P<indicator>[-+]?\d*|\d*[-+]?)\s*(?:\#.*)?$"""
)


def scan_yaml(text: str) -> Marks:
    comment: set[int] = set()
    offsets = line_offsets(text)
    lines = lines_of(text)
    index = 0

    while index < len(lines):
        line = lines[index]
        header = BLOCK_LINE.match(line)
        # A comment that happens to end in `: |` is a comment, not the start of a block scalar.
        if header is not None and not line.lstrip().startswith("#"):
            indent = len(line) - len(line.lstrip())
            start, index = _block_scalar(lines, index + 1, indent)
            key = (header.group("key") or "").strip().strip("\"'")
            if key == "run" and start < index:
                body = "\n".join(lines[start:index])
                for offset in scan_shell(body).comment:
                    comment.add(offsets[start] + offset)
            continue
        _mark_yaml_line(comment, line, offsets[index])
        index += 1

    return Marks(comment, set())


def _block_scalar(lines: list[str], start: int, indent: int) -> tuple[int, int]:
    end = start
    while end < len(lines):
        line = lines[end]
        if line.strip() and (len(line) - len(line.lstrip())) <= indent:
            break
        end += 1
    return start, end


def _mark_yaml_line(comment: set[int], line: str, offset: int) -> None:
    index, quote = 0, ""
    while index < len(line):
        char = line[index]
        if quote:
            quote = "" if char == quote else quote
        elif char in "'\"":
            quote = char
        elif char == "#" and (index == 0 or line[index - 1].isspace()):
            _span(comment, offset + index, offset + len(line))
            return
        index += 1


# --------------------------------------------------------------------------------------------
# Vue. Three languages in one file, and the top-level blocks are the ones at column 0.
# --------------------------------------------------------------------------------------------

OPENS: Final = re.compile(r"^<(template|script|style)\b", re.MULTILINE)
BINDING: Final = re.compile(r"^(?::|@|v-|#)")


def scan_vue(text: str) -> Marks:
    comment: set[int] = set()
    offsets = line_offsets(text)
    lines = lines_of(text)

    number = 0
    while number < len(lines):
        opened = OPENS.match(lines[number])
        if opened is None:
            number += 1
            continue
        kind = opened.group(1)
        closing = f"</{kind}>"
        end = number + 1
        while end < len(lines) and not lines[end].startswith(closing):
            end += 1
        body = "\n".join(lines[number + 1 : end])
        base = offsets[number + 1] if number + 1 < len(offsets) else len(text)
        if kind == "script":
            comment |= scan_javascript(body, base).comment
        elif kind == "style":
            comment |= _style(body, base)
        else:
            comment |= _markup(body, base)
        number = end + 1

    return Marks(comment, set())


def _style(text: str, base: int) -> set[int]:
    """CSS. A `/*` inside a string — a `content:` value, a data URI — opens nothing."""
    comment: set[int] = set()
    index = 0
    while index < len(text):
        char = text[index]
        if char in "'\"":
            index = _quoted(text, index, char, len(text))
            continue
        if text.startswith("/*", index):
            end = text.find("*/", index + 2)
            end = len(text) if end == -1 else end + 2
            _span(comment, base + index, base + end)
            index = end
            continue
        index += 1
    return comment


def _markup(text: str, base: int) -> set[int]:
    """The template. `<!--` is a comment; an attribute expression and a mustache hold JavaScript.

    Both halves are load-bearing. A `<!--` inside an attribute value is not a comment, and a `//`
    wall inside a `:class="[...]"` is one — the second was four lines long and invisible.
    """
    comment: set[int] = set()
    index, stop = 0, len(text)

    while index < stop:
        if text.startswith("<!--", index):
            end = text.find("-->", index + 4)
            end = stop if end == -1 else end + 3
            _span(comment, base + index, base + end)
            index = end
            continue
        if text.startswith("{{", index):
            end = text.find("}}", index + 2)
            end = stop if end == -1 else end
            _javascript(text, base, comment, index + 2, end)
            index = end + 2
            continue
        if text[index] == "<" and text[index + 1 : index + 2] not in ("", " "):
            index = _tag(text, base, comment, index, stop)
            continue
        index += 1

    return comment


def _tag(text: str, base: int, comment: set[int], index: int, stop: int) -> int:
    """Inside `<...>`. A quoted value on a binding attribute is scanned as JavaScript."""
    index += 1
    name = ""
    while index < stop:
        char = text[index]
        if char == ">":
            return index + 1
        if char in "'\"":
            # Not `_quoted`: that one ends at a newline, which is right for a JavaScript string
            # and wrong for an attribute, whose value is where the multi-line walls actually are.
            end = text.find(char, index + 1)
            end = stop if end == -1 else end
            if BINDING.match(name):
                _javascript(text, base, comment, index + 1, end)
            index = end + 1
            name = ""
            continue
        if char == "=":
            index += 1
            continue
        name = "" if char.isspace() else name + char
        index += 1
    return index


SCANNERS: Final = {
    ".py": scan_python,
    ".ts": scan_javascript,
    ".js": scan_javascript,
    ".vue": scan_vue,
    ".sh": scan_shell,
    ".yml": scan_yaml,
    ".yaml": scan_yaml,
}


# --------------------------------------------------------------------------------------------
# From marked characters to blocks.
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Block:
    path: Path
    start: int
    length: int
    kind: str
    first: str
    reason: str | None


def classify(text: str, marks: Marks) -> list[str]:
    """One verdict per line: `comment`, `documentation`, or `` for code and blank.

    A line carrying anything outside the marks is code, whatever else it also carries. That is the
    whole of the rule about a `#` in a URL: the line is not made of prose, so it is not counted.
    """
    offsets = line_offsets(text)
    verdicts: list[str] = []

    for number, line in enumerate(lines_of(text)):
        base = offsets[number]
        content = [base + column for column, char in enumerate(line) if not char.isspace()]
        if not content:
            verdicts.append("")
        elif all(position in marks.comment for position in content):
            verdicts.append("comment")
        elif all(position in marks.documentation for position in content):
            verdicts.append("documentation")
        else:
            verdicts.append("")

    return _drop_edge_delimiters(lines_of(text), verdicts)


def _drop_edge_delimiters(lines: list[str], verdicts: list[str]) -> list[str]:
    """`\"\"\"` and `*/` stop counting where they open and close a block, and nowhere else.

    Discounting them anywhere would hand over a way to saw a wall in half: a `/*` on a line of its
    own, in the middle of a comment, would split six lines of prose into two blocks of three.
    """
    result = list(verdicts)
    start = 0
    while start < len(result):
        if not result[start]:
            start += 1
            continue
        end = start
        while end < len(result) and result[end]:
            end += 1
        for edge in (range(start, end), reversed(range(start, end))):
            for number in edge:
                if not DELIMITER.match(lines[number].strip()):
                    break
                result[number] = ""
        start = end
    return result


def blocks_in(path: Path, text: str, verdicts: list[str]) -> Iterator[Block]:
    """Consecutive prose, whichever syntax carries it.

    A docstring followed straight away by a `#` comment is six lines of prose to the person
    reading it, and splitting them by kind would report two blocks of three.
    """
    lines = lines_of(text)
    start = 0
    while start < len(verdicts):
        if not verdicts[start]:
            start += 1
            continue
        end = start
        while end < len(verdicts) and verdicts[end]:
            end += 1
        first = lines[start].strip()
        yield Block(path, start + 1, end - start, verdicts[start], first, _reason(lines[start]))
        start = end


def _reason(first: str) -> str | None:
    found = MARKER.match(first)
    return found.group("reason").strip() if found is not None else None


def excused(block: Block) -> tuple[bool, str | None]:
    """Whether a block says why it is long, and whether what it says is a reason.

    The marker is refused rather than trusted when the clause after it is a word or two: an escape
    that costs nothing to write is an escape everything ends up using.
    """
    if block.reason is None:
        return False, None
    words = len(block.reason.split())
    if words < REASON_WORDS:
        return False, f"the clause after LONG BECAUSE is {words} word(s), which is not a reason"
    return True, None


# --------------------------------------------------------------------------------------------
# The tree, and what it owes.
# --------------------------------------------------------------------------------------------

GENERATED: Final = frozenset({Path("frontend/src/api/schema.d.ts")})
"""Written by `openapi-typescript` and checked by scripts/check-schema.sh. A rule about how a
person writes a comment has nothing to say about a file no person writes."""

DEBT: Final = Path("scripts/comment-debt.txt")
"""What the ceiling was written too late to prevent: blocks and prose lines, per file.

Both numbers, because either alone can be held still while the file gets worse. A wall added above
an existing one merges with it and leaves the count at three; the line total is what notices.

It only shrinks. A file gaining prose is a refusal, and a file losing it is also a refusal, since a
number left sitting above the truth stops meaning anything within a month. Both say what to run.
"""


def tracked() -> list[Path]:
    listing = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, text=True, check=True
    ).stdout
    named = (Path(name) for name in listing.split("\0") if name)
    return [path for path in named if path.suffix in SCANNERS and path not in GENERATED]


def read(path: Path) -> tuple[str, list[str]]:
    # utf-8-sig: a byte order mark is not a character, and leaving it in front of the first line
    # makes the tokenizer refuse the file and the gate report that it cannot judge anything.
    text = path.read_text(encoding="utf-8-sig")
    return text, classify(text, SCANNERS[path.suffix](text))


def survey(paths: list[Path]) -> list[Block]:
    found: list[Block] = []
    for path in paths:
        try:
            text, verdicts = read(path)
        except (SyntaxError, tokenize.TokenError, UnicodeDecodeError, ValueError) as cause:
            print(f"::error file={path}::cannot be read as {path.suffix}: {cause}")
            raise SystemExit(2) from cause
        found.extend(blocks_in(path, text, verdicts))
    return found


def over_ceiling(found: list[Block]) -> list[Block]:
    return [block for block in found if block.length > CEILING]


def read_debt() -> dict[str, tuple[int, int]]:
    if not DEBT.exists():
        return {}
    recorded: dict[str, tuple[int, int]] = {}
    for line in DEBT.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            count, lines, name = stripped.split(maxsplit=2)
            recorded[name.strip()] = (int(count), int(lines))
    return recorded


def write_debt(counts: dict[str, tuple[int, int]]) -> None:
    header = [
        "# Comment blocks over the ceiling, and the prose lines in them: `blocks lines path`.",
        "# Recorded where the rule arrived after the code, and it only shrinks — clear some, run",
        "# `python3 scripts/comments.py --update`, and the diff says what the file owed and owes.",
        "",
    ]
    body = [f"{count} {lines} {name}" for name, (count, lines) in sorted(counts.items())]
    DEBT.write_text("\n".join(header + body) + "\n", encoding="utf-8")


def offending(found: list[Block]) -> list[Block]:
    return [block for block in over_ceiling(found) if not excused(block)[0]]


def counted(found: list[Block]) -> dict[str, tuple[int, int]]:
    counts: dict[str, tuple[int, int]] = {}
    for block in offending(found):
        blocks, lines = counts.get(str(block.path), (0, 0))
        counts[str(block.path)] = (blocks + 1, lines + block.length)
    return counts


def report(found: list[Block]) -> int:
    counts = counted(found)
    recorded = read_debt()
    failures = 0

    for block in over_ceiling(found):
        allowed, why = excused(block)
        if not allowed and why is not None:
            print(f"::error file={block.path},line={block.start}::{why}")
            failures += 1

    for name in sorted(set(counts) | set(recorded)):
        now, before = counts.get(name, (0, 0)), recorded.get(name, (0, 0))
        if now == before:
            continue
        failures += 1
        if now > before:
            print(f"::error file={name}::{now[0]} block(s) over {CEILING} lines holding {now[1]} "
                  f"lines of prose; {before[0]} and {before[1]} recorded")
            for block in sorted((b for b in offending(found) if str(b.path) == name),
                                key=lambda b: b.start):
                print(f"    {name}:{block.start}  {block.length} lines  {block.first[:70]}")
        else:
            print(f"::error file={name}::{now[0]} block(s) holding {now[1]} lines now, "
                  f"{before[0]} and {before[1]} recorded — run: python3 scripts/comments.py --update")

    excuses = [b for b in over_ceiling(found) if excused(b)[0]]
    if excuses:
        print(f"\n    {len(excuses)} block(s) excused:")
        for block in sorted(excuses, key=lambda b: (str(b.path), b.start)):
            print(f"        {block.path}:{block.start}  {block.length} lines — {block.reason}")

    if failures == 0:
        print(f"    ok    no comment block over {CEILING} lines beyond the "
              f"{sum(count for count, _ in recorded.values())} recorded in {DEBT}")
    return failures


def measure(found: list[Block]) -> None:
    over = over_ceiling(found)
    kinds: dict[str, int] = {}
    lengths: dict[int, int] = {}
    for block in over:
        kinds[block.kind] = kinds.get(block.kind, 0) + 1
    for block in found:
        lengths[block.length] = lengths.get(block.length, 0) + 1
    print(f"blocks: {len(found)}   over {CEILING}: {len(over)}   in {len({b.path for b in over})} files")
    print(f"by kind: {kinds}")
    print("lengths: " + " ".join(f"{n}:{lengths[n]}" for n in sorted(lengths)))
    for block in sorted(over, key=lambda b: -b.length)[:20]:
        print(f"  {block.length:>3}  {block.kind:<13} {block.path}:{block.start}")


# --------------------------------------------------------------------------------------------
# The scanners' own cases: shapes a pattern gets wrong, most found breaking an earlier draft.
# --------------------------------------------------------------------------------------------

CASES: Final = (
    # Python: the tokenizer decides, so a `#` inside a string is text.
    ("py", 'x = "# not a comment"\n', "."),
    ("py", "# a comment\n", "c"),
    ("py", "x = 1  # trailing\n", "."),
    ("py", '"""Summary.\n\n#b\n"""\n', "d.d."),
    ("py", 'NAME = "x"\n"""Prose under an attribute."""\n', ".d"),
    ("py", "x = f\"{'#'}\"  # after\n", "."),
    ("py", 'x = """\n# inside\n"""\n', "..."),
    # `ast` counts columns in bytes: a docstring ending in Cyrillic used to eat the code below it.
    ("py", 'def f():\n    """Обновляет состояние."""\n    a = 1\n    b = 2\n', ".d.."),
    ("py", 'def f():\n    """Ends in an em dash —"""\n    a = 1\n', ".d."),
    # `str.splitlines` breaks on these and Python does not, so the two numberings disagreed.
    ("py", 'X = "a\x0cb"\ny = 1\n# real\n', "..c"),
    ("py", 'X = "a b"\n# real\n', ".c"),
    # A line inside a block that merely looks like a delimiter must not split it.
    ("py", '"""One.\n/*\nThree.\nFour."""\n', "dddd"),
    # JavaScript: the four things that can hold a slash.
    ("ts", "const u = 'https://example.test/x'\n", "."),
    ("ts", "// a comment\n", "c"),
    ("ts", "const r = /a\\/\\/b/\n", "."),
    ("ts", "const q = a / b / c\n", "."),
    ("ts", "return /x/.test(s)\n", "."),
    ("ts", "throw /ab[/*]cd/\n// real\n", ".c"),
    ("ts", "const t = `a ${'//'} b`\n", "."),
    ("ts", "const t = `${\n  // a comment\n  x\n}`\n", ".c.."),
    ("ts", "/* one\n   two */\n", "cc"),
    ("ts", "const x = 1 // trailing\n", "."),
    ("ts", "/** doc */\n", "c"),
    ("ts", 'const s = "a b"\n// real\n', ".c"),
    # Shell: `#` opens a comment only at the start of a word, and `<<` is rarely a heredoc.
    ("sh", "echo $#\n", "."),
    ("sh", 'echo "${x#prefix}"\n', "."),
    ("sh", "# a comment\n", "c"),
    ("sh", "echo a#b\n", "."),
    ("sh", "echo '# quoted'\n", "."),
    ("sh", "cat <<EOF\n# inside a heredoc\nEOF\n# real\n", "...c"),
    ("sh", 'done <<<"$offenders"\n# real\n', ".c"),
    ("sh", "cat <<\\EOF\n# data\nEOF\n# real\n", "...c"),
    ("sh", "n=$((1 << 3))\n# real\n", ".c"),
    ("sh", "cat <<EOF\n  EOF\nstill data\nEOF\n# real\n", "....c"),
    ("sh", "x=$'a\\'b'\n# real\n", ".c"),
    ("sh", "echo a \\\n# a comment on the continued line\n", ".c"),
    # The parity flip: the outer string must not close on a `"` that belongs to the `$( )`.
    ("sh", 'x="$(grep -e \'a\' | grep -v "^${T}$" || true)"\n# real\n', ".c"),
    ("sh", 'x="$(echo "a" && echo \'b\')"\ny="$(echo "c")"\n# real\n', "..c"),
    # YAML, and the shell inside a `run:` block.
    ("yml", "key: a#b\n", "."),
    ("yml", 'key: "x # y"\n', "."),
    ("yml", "# a comment\n", "c"),
    ("yml", "run: |\n  # shell comment\n  echo hi\n", ".c."),
    ("yml", "name: |\n  # not shell\n", ".."),
    ("yml", "pre-run: |\n  # not shell\n", ".."),
    ("yml", "run: | # why\n  # shell comment\n", ".c"),
    ("yml", "run: &anchor |\n  # shell comment\n", ".c"),
    ("yml", "steps:\n  - |\n    # data\n", "..."),
    ("yml", "# a comment ending in a pipe: |\n# second\n# third\n", "ccc"),
    # Vue: three languages, and the top-level blocks are the ones at column 0.
    ("vue", "<template>\n  <!-- a comment -->\n  <p>x</p>\n</template>\n", ".c.."),
    ("vue", "<script setup>\n// a comment\nconst u = 'a//b'\n</script>\n", ".c.."),
    ("vue", "<style>\n/* a comment */\n.x { color: red }\n</style>\n", ".c.."),
    ("vue", '<style>\n.x { content: "/*" }\n.y { color: red }\n</style>\n', "...."),
    # A nested <template> is a v-for, not the end of the block: everything after it used to be
    # invisible, which is 27 lines of DashboardView.vue.
    ("vue", "<template>\n  <template v-for=\"x in y\">\n    <p>a</p>\n  </template>\n"
            "  <!-- a comment -->\n</template>\n", "....c."),
    # A `//` wall inside an attribute expression is a comment; a `<!--` inside one is not.
    ("vue", '<template>\n  <div\n    :class="[\n      // one\n      // two\n    ]"\n  />\n'
            "</template>\n", "...cc..."),
    ("vue", '<template>\n  <p title="a <!-- b">x</p>\n  <p>y</p>\n</template>\n', "...."),
)
"""One character of expectation per line of input: `c` comment, `d` prose, `.` neither."""

MARKERS: Final = (
    ("// LONG BECAUSE: a clause with enough words in it", "a clause with enough words in it"),
    ("# LONG BECAUSE: a clause with enough words in it", "a clause with enough words in it"),
    (" * LONG BECAUSE: a clause with enough words in it", "a clause with enough words in it"),
    ("<!-- LONG BECAUSE: a clause with enough words -->", "a clause with enough words"),
    ("LONG BECAUSE: a clause with enough words in it", "a clause with enough words in it"),
    ("// nothing to declare", None),
)

BLOCKS: Final = (
    # Prose is prose whichever syntax carries it: a docstring meeting a comment is one wall.
    ('"""One.\nTwo.\nThree."""\n# Four.\n', 1, 4),
    # A blank line ends a run, which is the rule as written and the one hole left open.
    ("# One.\n# Two.\n\n# Three.\n# Four.\n", 1, 2),
)


def self_test() -> int:
    failures = 0

    for suffix, text, expected in CASES:
        verdicts = classify(text, SCANNERS[f".{suffix}"](text))
        if text.endswith("\n"):
            verdicts = verdicts[:-1]
        got = "".join({"comment": "c", "documentation": "d"}.get(v, ".") for v in verdicts)
        if got != expected:
            failures += 1
            print(f"    FAILED  .{suffix}  expected {expected!r}, got {got!r}  from {text!r}")

    for line, expected in MARKERS:
        if _reason(line) != expected:
            failures += 1
            print(f"    FAILED  marker  expected {expected!r}, got {_reason(line)!r}  from {line!r}")

    for text, start, length in BLOCKS:
        found = list(blocks_in(Path("case"), text, classify(text, scan_python(text))))
        first = found[0] if found else None
        if first is None or (first.start, first.length) != (start, length):
            failures += 1
            print(f"    FAILED  block   expected {(start, length)}, got "
                  f"{(first.start, first.length) if first else None}  from {text!r}")

    total = len(CASES) + len(MARKERS) + len(BLOCKS)
    print(f"{failures} of {total} cases failed" if failures else f"    ok    {total} scanner cases")
    return failures


def main(argv: list[str]) -> int:
    # Before it judges anything. A scanner that has stopped telling a comment from a URL would
    # report a repository full of violations, or none, and both look like an answer.
    if self_test():
        print("::error file=scripts/comments.py::the scanners fail their own cases; judging nothing")
        return 2
    if "--self-test" in argv:
        return 0

    found = survey(tracked())

    if "--measure" in argv:
        measure(found)
        return 0

    if "--update" in argv:
        counts = counted(found)
        write_debt(counts)
        print(f"recorded {sum(c for c, _ in counts.values())} block(s) "
              f"holding {sum(n for _, n in counts.values())} lines in {len(counts)} file(s)")
        return 0

    return 1 if report(found) else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
