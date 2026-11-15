#!/usr/bin/env python3
"""Find real people's data and private references in text before it reaches GitHub.

The repo, its issues and the project board are public, and the pilot gym's real
members live on staging. This scans text for three things:

* **Patterns**, which need no list: a Chilean RUT with a valid check digit, a
  Chilean mobile number, an email whose domain is not on `EMAIL_DOMAINS` (#302),
  and an absolute path on someone's machine (`/Volumes/…`, `/Users/<name>`,
  `/home/<name>`, `C:\\Users\\…`, `~/<folder>` outside `HOME_PATHS_OK`) (#324).
* **The denylist**: the real names, emails, RUTs and phones the PM exports from
  staging. It never enters the repo. It is read from `--denylist`, else the
  `PII_DENYLIST` variable (its content, as CI's secret is), else the file named
  by `PII_DENYLIST_FILE`, else `~/.config/rakin/pii-denylist.txt`.
* **The private terms**: the owner's private project and repo names, internal
  ticket prefixes and client names, matched as whole words (#324). Kept outside
  the repo like the denylist: `--terms`, else `PRIVATE_TERMS` (content), else
  `PRIVATE_TERMS_FILE`, else `~/.config/rakin/private-terms.txt`.

A hit prints `<where>:<line>:<col>: <kind>` and never the matched text, so a CI
log or a hook's refusal cannot leak what it found. Exit status: 0 clean, 1 a
hit, 2 a usage error.

Usage:
  pii_guard.py scan [--name LABEL] [FILE|-]...   # files, or stdin as LABEL
  pii_guard.py scan --jsonl FILE|-               # {"label":…, "text":…} per line
  pii_guard.py diff [--range A...B] [-]          # added lines of a diff
  pii_guard.py staged                            # the staged diff (pre-commit)
  pii_guard.py commit-msg FILE                   # a commit message (commit-msg)
  pii_guard.py tree                              # every tracked file
  pii_guard.py claude-hook                       # Claude Code PreToolUse on Bash

Invented values are marked, not hidden: a line containing `pii-ok` skips the
pattern checks, and so does a file under `FIXTURE_PATHS`. Neither skips the
denylist or the private terms, which only ever hold real things.

Stdlib only: run it with `python3 -I` or `uv run`. See docs/privacy-guard.md.
"""

from __future__ import annotations

import argparse
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field, replace
from pathlib import Path

# Domains that only ever hold invented addresses, each with its subdomains.
# `example.cl` is this repo's own convention for a test address.
EMAIL_DOMAINS = (
    "example.com",
    "example.org",
    "example.net",
    "example.cl",
    "example",
    "test",
    "invalid",
    "localhost",
    "rakin.app",
    "rakin.test",
    "users.noreply.github.com",
    "noreply.github.com",
    "github.com",
    "anthropic.com",
)

# Files whose RUTs, phones and emails are invented on purpose: the test suites
# and the demo gym. Matched with fnmatch against the repo-relative path.
FIXTURE_PATHS = (
    "backend/tests/*",
    "backend/app/seed/*",
    "frontend/src/*.test.ts",
    "frontend/src/*.test.tsx",
    "scripts/test_pii_guard.py",
    "*package-lock.json",
    "*uv.lock",
)

# The textbook examples the code's own docstrings and READMEs quote. Canonical
# form: digits, then the check digit, as `canonical_number` gives it.
EXAMPLE_VALUES = frozenset(
    {
        "123456785",  # 12.345.678-5
        "761234560",  # 76.123.456-0
        "76123456k",
        "76543216",  # 7.654.321-6
        "111111111",  # 11.111.111-1
        "10000013k",  # 10.000.013-K
        "764321090",
        "76432109k",  # the demo gym's company RUT
        "912345678",  # 9 1234 5678
        "987654321",  # 9 8765 4321
        "900000001",  # the placeholder owner phone a new gym starts with
        "955551234",
    }
)
# The demo gym's phones, 9 6123 4501 and on (backend/app/seed/demo_import.csv).
EXAMPLE_PREFIXES = ("9612345",)

MARK = "pii-ok"
# Commit-message lines that repeat the commit's own metadata: `Signed-off-by:`
# and friends, and the `# Author:` / `# Date:` lines of git's editor template.
# The patterns skip them, so a committer's address passes; the denylist does not.
METADATA = re.compile(
    r"^(?:[A-Za-z][A-Za-z-]*-by:|#\s*(?:Author|Date|Committer):)\s", re.IGNORECASE
)
SCISSORS = re.compile(r"^# -+ >8 -+", re.MULTILINE)

SEP = r"[ \t.\-]*"
RUT = re.compile(r"(?<![\w.])(\d{1,2}\.\d{3}\.\d{3}|\d{7,8})-([\dkK])(?![\w])")
PHONE = re.compile(rf"(?<![\w+])(?:(?:\+|00)?56{SEP})?\(?9\)?{SEP}\d{{4}}{SEP}\d{{4}}(?![\w])")
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,})")
# An absolute path on a machine: a mounted volume, a home directory on macOS,
# Linux or Windows, or `~/` and a folder. A placeholder (`/Users/<name>`,
# `/Volumes/…`) does not start with a name character, so it passes. On Linux the
# path needs a folder under the user's (`/home/<name>/…`), so a one-segment web
# route such as `/home/clases` is not taken for one.
NAME = r"[\w.-]"
LOCAL_PATH = re.compile(
    rf"(?<![\w.~-])/(?:Volumes/|Users/|home/{NAME}+/){NAME}"
    rf"|(?<![\w])[A-Za-z]:(?:\\{{1,2}}|/)Users(?:\\{{1,2}}|/){NAME}"
)
HOME_PATH = re.compile(r"(?<![\w~/$.-])~/([\w.-][^\s'\"`()<>|;:,*]*)")
# Home folders that name nothing private: the guard's own lists, task-force's
# state, and the standard tool folders CI and the docs use. Each matches as a
# whole leading segment.
HOME_PATHS_OK = (".config/rakin", ".task-force", ".ssh", ".local/bin", ".kiro")
NUMBER = re.compile(r"\+?\(?\d+(?:[ \t.\-()]{1,2}\d+)*(?:-[kK])?")
WORD = re.compile(r"[a-z0-9]+")

DEFAULT_DENYLIST = Path("~/.config/rakin/pii-denylist.txt")
DEFAULT_TERMS = Path("~/.config/rakin/private-terms.txt")


def fold(text: str) -> str:
    """Lowercase without accents: `Ñuñoa` and `nunoa` are one word."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).casefold()


def canonical_number(text: str) -> str:
    """Digits and a trailing `k`, with a Chilean country code dropped."""
    digits = re.sub(r"[^0-9kK]", "", text).lower()
    for prefix in ("0056", "56"):
        if digits.startswith(prefix) and len(digits) == len(prefix) + 9:
            return digits[len(prefix) :]
    return digits


def rut_is_valid(body: str, dv: str) -> bool:
    digits = body.replace(".", "")
    total, factor = 0, 2
    for d in reversed(digits):
        total += int(d) * factor
        factor = 2 if factor == 7 else factor + 1
    expected = 11 - total % 11
    check = {11: "0", 10: "k"}.get(expected, str(expected))
    return dv.lower() == check


@dataclass(frozen=True)
class Denylist:
    phrases: tuple[tuple[str, ...], ...] = ()
    words: frozenset[str] = frozenset()
    emails: frozenset[str] = frozenset()
    numbers: frozenset[str] = frozenset()
    source: str = ""
    # The private terms (#324): each a tuple of folded words, matched whole.
    terms: tuple[tuple[str, ...], ...] = field(default=(), repr=False)

    def __bool__(self) -> bool:
        return bool(self.phrases or self.words or self.emails or self.numbers or self.terms)

    @classmethod
    def parse(cls, text: str, source: str = "") -> Denylist:
        """One entry per line; `#` starts a comment.

        A name of two or more words matches only as that whole sequence. A
        single word is ignored unless written `word: <it>`, since a lone common
        first name would fire everywhere. `Surnames, Given names` matches in both
        orders. A RUT or phone needs at least 8 digits, since a shorter one would
        fire inside unrelated numbers.
        """
        phrases, words, emails, numbers = set(), set(), set(), set()
        for n, raw in enumerate(text.splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line:
                continue
            if line.lower().startswith("word:"):
                words.update(WORD.findall(fold(line[5:])))
            elif "@" in line:
                emails.add(fold(line))
            elif sum(c.isdigit() for c in line) >= 7:
                canon = canonical_number(line)
                if len(canon) >= 8:
                    numbers.add(canon)
                else:
                    print(
                        f"pii-guard: denylist line {n} is under 8 digits, ignored", file=sys.stderr
                    )
            else:
                last, comma, first = line.partition(",")
                tokens = tuple(WORD.findall(fold(f"{first} {last}" if comma else line)))
                if len(tokens) >= 2:
                    phrases.add(tokens)
                    if comma:
                        phrases.add(tuple(WORD.findall(fold(f"{last} {first}"))))
                elif tokens:
                    print(
                        f"pii-guard: denylist line {n} is a single word, ignored"
                        " (write `word: …` to match it alone)",
                        file=sys.stderr,
                    )
        return cls(
            tuple(sorted(phrases)), frozenset(words), frozenset(emails), frozenset(numbers), source
        )

    @staticmethod
    def parse_terms(text: str) -> tuple[tuple[str, ...], ...]:
        """One term per line; `#` starts a comment. Under 3 letters is ignored."""
        terms = set()
        for n, raw in enumerate(text.splitlines(), 1):
            tokens = tuple(WORD.findall(fold(raw.split("#", 1)[0])))
            if sum(map(len, tokens)) >= 3:
                terms.add(tokens)
            elif tokens:
                print(
                    f"pii-guard: private terms line {n} is under 3 letters, ignored",
                    file=sys.stderr,
                )
        return tuple(sorted(terms))

    @classmethod
    def load(cls, path: str | None = None, terms_path: str | None = None) -> Denylist:
        denylist = cls()
        text = read_list(path, "PII_DENYLIST", DEFAULT_DENYLIST)
        if text:
            denylist = cls.parse(*text)
        terms = read_list(terms_path, "PRIVATE_TERMS", DEFAULT_TERMS)
        if terms:
            denylist = replace(denylist, terms=cls.parse_terms(terms[0]))
        return denylist


def read_list(path: str | None, var: str, default: Path) -> tuple[str, str] | None:
    """`(content, source)` from `path`, else `$VAR` (the content), else the file
    `$VAR_FILE` names, else `default`; None when there is none."""
    if path:
        return Path(path).expanduser().read_text(encoding="utf-8"), path
    content = os.environ.get(var)
    if content:
        return content, f"${var}"
    named = os.environ.get(f"{var}_FILE")
    candidate = Path(named).expanduser() if named else default.expanduser()
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8"), str(candidate)
    return None


@dataclass(frozen=True)
class Hit:
    where: str
    line: int
    col: int
    kind: str

    def __str__(self) -> str:
        return f"{self.where}:{self.line}:{self.col}: {self.kind}"


def is_fixture(path: str) -> bool:
    return any(fnmatch.fnmatch(path, pattern) for pattern in FIXTURE_PATHS)


def email_allowed(domain: str) -> bool:
    domain = domain.lower()
    return any(domain == d or domain.endswith("." + d) for d in EMAIL_DOMAINS)


def is_example(match: str) -> bool:
    canon = canonical_number(match)
    return canon in EXAMPLE_VALUES or canon.startswith(EXAMPLE_PREFIXES)


def home_path_allowed(path: str) -> bool:
    path = path.rstrip(".")
    if ".." in path.split("/"):
        return False
    return any(path == ok or path.startswith(ok + "/") for ok in HOME_PATHS_OK)


def scan_line(line: str, denylist: Denylist, patterns: bool = True) -> Iterator[tuple[int, str]]:
    """Yield `(column, kind)` for each match on one line."""
    if patterns and MARK not in line:
        for m in LOCAL_PATH.finditer(line):
            yield m.start() + 1, "local-path"
        for m in HOME_PATH.finditer(line):
            if not home_path_allowed(m.group(1)):
                yield m.start() + 1, "local-path"
        for m in RUT.finditer(line):
            if rut_is_valid(m.group(1), m.group(2)) and not is_example(m.group(0)):
                yield m.start() + 1, "rut"
        for m in PHONE.finditer(line):
            if not is_example(m.group(0)):
                yield m.start() + 1, "phone"
        for m in EMAIL.finditer(line):
            if not email_allowed(m.group(1)):
                yield m.start() + 1, "email"
    if not denylist:
        return
    folded = fold(line)
    for email in denylist.emails:
        at = folded.find(email)
        if at >= 0:
            yield at + 1, "denylist email"
    if denylist.numbers:
        for m in NUMBER.finditer(line):
            canon = canonical_number(m.group(0))
            if any(entry in canon for entry in denylist.numbers):
                yield m.start() + 1, "denylist number"
    if denylist.phrases or denylist.words or denylist.terms:
        spans = [(m.group(0), m.start()) for m in WORD.finditer(folded)]
        tokens = [t for t, _ in spans]
        width = max(map(len, denylist.terms + denylist.phrases), default=1)
        for i, (token, at) in enumerate(spans):
            window = tuple(tokens[i : i + width])
            if any(window[: len(term)] == term for term in denylist.terms):
                yield at + 1, "private-term"
            if token in denylist.words:
                yield at + 1, "denylist name"
                continue
            for phrase in denylist.phrases:
                if window[: len(phrase)] == phrase:
                    yield at + 1, "denylist name"
                    break


def scan_text(
    where: str, text: str, denylist: Denylist, *, first_line: int = 1, metadata: bool = False
) -> list[Hit]:
    """Scan each line; with `metadata`, `METADATA` lines get the denylist only."""
    fixture = is_fixture(where)
    hits = []
    for n, line in enumerate(text.splitlines(), first_line):
        patterns = not fixture and not (metadata and METADATA.match(line))
        hits.extend(Hit(where, n, col, kind) for col, kind in scan_line(line, denylist, patterns))
    return hits


def scan_diff(diff: str, denylist: Denylist) -> list[Hit]:
    """Scan only the lines a unified diff adds, at their new line numbers."""
    hits: list[Hit] = []
    path, line_no = "", 0
    for line in diff.splitlines():
        if line.startswith("+++ "):
            target = line[4:].split("\t", 1)[0]
            if target.startswith('"') and target.endswith('"'):
                target = target[1:-1]
            path = target[2:] if target.startswith("b/") else target
        elif line.startswith("@@"):
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)", line)
            line_no = int(m.group(1)) if m else 0
        elif line.startswith("+") and path != "/dev/null":
            hits.extend(scan_text(path, line[1:], denylist, first_line=line_no))
            line_no += 1
        elif line.startswith(" "):
            line_no += 1
    return hits


def git(*args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.quotePath=false", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    ).stdout


DIFF_ARGS = ("--no-color", "--no-ext-diff", "--no-textconv", "-U0", "--diff-filter=d")


def read_input(name: str) -> str:
    if name == "-":
        return sys.stdin.read()
    return Path(name).read_text(encoding="utf-8", errors="replace")


def looks_binary(data: bytes) -> bool:
    return b"\0" in data[:8192]


def scan_tree(denylist: Denylist) -> list[Hit]:
    hits = []
    for path in git("ls-files", "-z").split("\0"):
        if not path or not os.path.isfile(path):
            continue
        data = Path(path).read_bytes()
        if not looks_binary(data):
            hits.extend(scan_text(path, data.decode("utf-8", errors="replace"), denylist))
    return hits


# `gh` calls that can write to GitHub. Reads are scanned too: a read's command
# line holds nothing worth stopping, and telling them apart is fragile.
GH_CALL = re.compile(r"(?:^|[\s;&|(`$])gh\s+(?:issue|pr|api|release)\b")
FILE_FLAG = re.compile(r"(?:--body-file|--notes-file|--input|-F)(?:=|\s+)(\"[^\"]*\"|'[^']*'|\S+)")
FIELD_FILE = re.compile(
    r"(?:-F|--field|-f|--raw-field)(?:=|\s+)[\"']?[\w.\[\]-]+=@(\"[^\"]*\"|'[^']*'|[^\s\"']+)"
)
# `--body "$(cat b.md)"`, `$(<b.md)` and the backtick form: a file read into an argument.
CAT_FILE = re.compile(r"(?:\$\(|`)\s*(?:cat\s+|<\s*)(\"[^\"]*\"|'[^']*'|[^\s)`\"']+)\s*(?:\)|`)")
# `cd <dir>` at the start of a command: where it runs, which never reaches GitHub.
CD_DIR = re.compile(r"(?:^|[;&|(\n])\s*cd\s+(\"[^\"]*\"|'[^']*'|[^\s;&|)]+)")
HEREDOC = re.compile(r"<<-?\s*['\"]?\w+")
UNREADABLE = "unreadable body file, not scanned: write it to a literal path first"


def gh_file_args(command: str) -> list[tuple[str, tuple[int, int]]]:
    """Each file a gh command reads its body from (`-` and fields excluded),
    with the span of its path in the command."""
    found = []
    for m in FIELD_FILE.finditer(command):
        found.append((m.group(1), m.span(1)))
    for m in CAT_FILE.finditer(command):
        found.append((m.group(1), m.span(1)))
    for m in FILE_FLAG.finditer(command):
        value = m.group(1)
        if "=" in value.strip("\"'") and not value.startswith(('"', "'", "/", ".", "~")):
            continue  # `-F key=value` is a field, handled above when it is `=@file`
        found.append((value, m.span(1)))
    paths = []
    for value, span in found:
        try:
            value = shlex.split(value)[0]
        except (ValueError, IndexError):
            value = value.strip("\"'")
        if value and value != "-":
            paths.append((value, span))
    return paths


def gh_files(command: str) -> list[str]:
    return [path for path, _ in gh_file_args(command)]


def quote_states(command: str) -> list[str]:
    """The shell quote open before each character: `""`, `"'"` or `'"'`."""
    states, quote, escaped = [], "", False
    for c in command:
        states.append(quote)
        if escaped:
            escaped = False
        elif c == "\\" and quote != "'":
            escaped = True
        elif quote and c == quote:
            quote = ""
        elif not quote and c in "'\"":
            quote = c
    return states


def published_text(command: str) -> str:
    """The command with the paths it only reads blanked out: its body files and
    `cd` targets. Those stay on the machine, so a local path there is fine;
    blanking keeps every other column where it was.

    Only shell words are blanked, never text that gets posted: nothing inside a
    heredoc's body, and nothing inside a quoted argument (`--body "…cd /x…"`),
    except a `$(cat file)` in double quotes, which the shell runs."""
    heredoc = HEREDOC.search(command)
    body = command.find("\n", heredoc.end()) if heredoc else -1
    limit = body if body >= 0 else len(command)
    states = quote_states(command[:limit])
    spans = [(m.span(1), "'") for m in CAT_FILE.finditer(command)]
    spans += [(span, "'\"") for _, span in gh_file_args(command)]
    spans += [(m.span(1), "'\"") for m in CD_DIR.finditer(command)]
    chars = list(command)
    for (start, end), quoted in spans:
        if end <= limit and (not states[start] or states[start] not in quoted):
            chars[start:end] = " " * (end - start)
    return "".join(chars)


def claude_hook(denylist: Denylist, payload: dict) -> list[Hit]:
    if payload.get("tool_name") != "Bash":
        return []
    command = str((payload.get("tool_input") or {}).get("command") or "")
    if not GH_CALL.search(command):
        return []
    hits = scan_text("command", published_text(command), denylist)
    cwd = Path(payload.get("cwd") or os.getcwd())
    for name in gh_files(command):
        # Fail closed: a file the hook cannot find (an unexpanded `$VAR`, a `$(…)`
        # path, one the command itself writes first) would go out unscanned.
        expanded = os.path.expandvars(os.path.expanduser(name))
        path = (cwd / expanded).resolve()
        if "$" in expanded or "`" in expanded or not path.is_file():
            hits.append(Hit(name, 0, 0, UNREADABLE))
            continue
        hits.extend(scan_text(name, path.read_text(encoding="utf-8", errors="replace"), denylist))
    return hits


def report(hits: list[Hit], *, out=sys.stderr) -> int:
    if not hits:
        return 0
    seen = set()
    print(
        "pii-guard: possible personal or private data found (values are never printed):", file=out
    )
    for hit in hits:
        if str(hit) not in seen:
            seen.add(str(hit))
            print(f"  {hit}", file=out)
    print(
        "\n  Replace it with an invented value, and a local path with a repo-relative one."
        f" A deliberate\n  fixture line takes a `{MARK}` comment. A denylist hit is a real"
        " person and a private-term\n  hit is the owner's private work: neither has an"
        " override. See docs/privacy-guard.md.",
        file=out,
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="pii_guard.py", description=(__doc__ or "").split("\n\n")[0]
    )
    parser.add_argument("--denylist", help="denylist file (default: see module doc)")
    parser.add_argument("--terms", help="private terms file (default: see module doc)")
    parser.add_argument(
        "--no-denylist", action="store_true", help="patterns only: no denylist, no private terms"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_scan = sub.add_parser("scan")
    p_scan.add_argument("--name", default="stdin", help="label for stdin in the output")
    p_scan.add_argument("--jsonl", help='file of {"label": …, "text": …} records, or -')
    p_scan.add_argument("files", nargs="*")
    p_diff = sub.add_parser("diff")
    p_diff.add_argument("--range", help="git range to diff, e.g. BASE...HEAD")
    p_diff.add_argument("file", nargs="?", default="-")
    sub.add_parser("staged")
    p_msg = sub.add_parser("commit-msg")
    p_msg.add_argument("file")
    sub.add_parser("tree")
    sub.add_parser("claude-hook")
    args = parser.parse_args(argv)

    denylist = Denylist() if args.no_denylist else Denylist.load(args.denylist, args.terms)

    if args.cmd == "scan":
        hits = []
        if args.jsonl:
            for n, raw in enumerate(read_input(args.jsonl).splitlines(), 1):
                if raw.strip():
                    record = json.loads(raw)
                    hits += scan_text(
                        str(record.get("label") or f"record{n}"),
                        str(record.get("text") or ""),
                        denylist,
                    )
        for name in args.files or ([] if args.jsonl else ["-"]):
            hits += scan_text(args.name if name == "-" else name, read_input(name), denylist)
        return report(hits)
    if args.cmd == "diff":
        diff = git("diff", *DIFF_ARGS, args.range) if args.range else read_input(args.file)
        return report(scan_diff(diff, denylist))
    if args.cmd == "staged":
        return report(scan_diff(git("diff", "--cached", *DIFF_ARGS), denylist))
    if args.cmd == "commit-msg":
        text = read_input(args.file)
        # `#` lines are scanned: `git commit -m` and `-F` keep them (cleanup is
        # `whitespace` without an editor), and the hook cannot tell which ran.
        # Only the scissors tail is certain to go.
        text = SCISSORS.split(text, maxsplit=1)[0]
        return report(scan_text("commit message", text, denylist, metadata=True))
    if args.cmd == "tree":
        return report(scan_tree(denylist))
    if args.cmd == "claude-hook":
        hits = claude_hook(denylist, json.load(sys.stdin))
        # Exit 2 is Claude Code's "block this call"; stderr becomes the reason.
        return 2 if report(hits) else 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
