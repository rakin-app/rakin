"""Tests for pii_guard.py: `python3 -m unittest discover -s scripts`.

Every RUT, phone, name, path and private term here is invented. The file is
under the script's `FIXTURE_PATHS`, so its own diff passes the guard. The real
lists are kept out: every run points them at a missing file.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pii_guard as g

SCRIPT = Path(__file__).resolve().parent / "pii_guard.py"
LISTS = ("PII_DENYLIST", "PRIVATE_TERMS")
NO_LISTS = {"PII_DENYLIST_FILE": "/nonexistent", "PRIVATE_TERMS_FILE": "/nonexistent"}
NONE = g.Denylist()
with redirect_stderr(io.StringIO()):
    NAMES = g.Denylist.parse(
        "\n".join(
            [
                "# the PM's export",
                "Ximena Ñúñez Peñaloza",
                "Bastián Quezada",
                "word: Zúñiga",
                "Rocío",  # a single word without `word:`: ignored
                "ximena.real@gmail.com",
                "21.333.444-K",
                "+56 9 7777 1234",
            ]
        )
    )
VALID_RUT = "15.234.871-1"
VALID_RUT_PLAIN = "15234871-1"
WRONG_RUT = "15.234.871-2"


def kinds(text: str, denylist: g.Denylist = NONE, where: str = "notes.md") -> list[str]:
    return [hit.kind for hit in g.scan_text(where, text, denylist)]


def run(*args: str, stdin: str = "", env: dict | None = None, cwd: str | None = None):
    full_env = {k: v for k, v in os.environ.items() if not k.startswith(LISTS)}
    full_env.update(NO_LISTS)
    full_env.update(env or {})
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args],
        input=stdin,
        capture_output=True,
        text=True,
        env=full_env,
        cwd=cwd,
    )


class Rut(unittest.TestCase):
    def test_valid_check_digit_in_both_forms(self):
        self.assertEqual(kinds(f"RUT {VALID_RUT}"), ["rut"])
        self.assertEqual(kinds(f"rut={VALID_RUT_PLAIN};"), ["rut"])

    def test_k_check_digit(self):
        self.assertEqual(kinds("19.654.321-K y 19654321-k"), ["rut", "rut"])

    def test_wrong_check_digit_is_not_a_rut(self):
        self.assertEqual(kinds(f"RUT {WRONG_RUT}"), [])
        self.assertEqual(kinds("15234871-2"), [])

    def test_not_inside_longer_numbers(self):
        self.assertEqual(kinds("v1.15.234.871-1 x115234871-1"), [])

    def test_textbook_examples_pass(self):
        self.assertEqual(kinds("`12.345.678-5`, `77312456-0`, `7.654.321-6`"), [])


class Phone(unittest.TestCase):
    def test_variants(self):
        for phone in [
            "+56 9 7312 4501",
            "+56973124501",
            "56 9 7312 4501",
            "0056 9 7312 4501",
            "9 7312 4501",
            "973124501",
            "(9) 7312-4501",
            "97312 4501",
            "+56-9-7312-4501",
        ]:
            with self.subTest(phone=phone):
                self.assertEqual(kinds(f"llamar al {phone} hoy"), ["phone"])

    def test_not_a_mobile(self):
        for text in ["+56 2 2123 4567", "8 7312 4501", "1973124501", "id 9731245012"]:
            with self.subTest(text=text):
                self.assertEqual(kinds(text), [])

    def test_textbook_examples_pass(self):
        self.assertEqual(kinds("`+56 9 1234 5678`, `912345678`, `9 8765 4321`"), [])
        self.assertEqual(kinds("demo: 9 6123 4501, +56961234542"), [])


class Email(unittest.TestCase):
    def test_unlisted_domain(self):
        self.assertEqual(kinds("write to someone@gmail.com"), ["email"])
        self.assertEqual(kinds("Some.One@Hotmail.CL"), ["email"])

    def test_allowlisted_domains_and_subdomains(self):
        text = (
            "a@example.com b@example.org c@example.cl d@rakin.app e@rakin.test "
            "f@academiasur.example.com 1+x@users.noreply.github.com noreply@anthropic.com"
        )
        self.assertEqual(kinds(text), [])


class Folding(unittest.TestCase):
    def test_case_and_accents(self):
        self.assertEqual(g.fold("Ñuñoa ÁLVAREZ"), "nunoa alvarez")
        self.assertEqual(kinds("ximena nunez penaloza vino", NAMES), ["denylist name"])
        self.assertEqual(kinds("XIMENA ÑÚÑEZ PEÑALOZA", NAMES), ["denylist name"])

    def test_name_inside_an_identifier_or_email(self):
        self.assertEqual(kinds("bastian_quezada.csv", NAMES), ["denylist name"])
        self.assertEqual(kinds("bastian.quezada@example.cl", NAMES), ["denylist name"])


class FullNameVersusWord(unittest.TestCase):
    def test_part_of_a_full_name_does_not_match(self):
        self.assertEqual(kinds("Ximena Ñúñez vino", NAMES), [])
        self.assertEqual(kinds("Bastián vino; Quezada no", NAMES), [])

    def test_single_word_only_when_listed_as_one(self):
        self.assertEqual(kinds("la familia Zuniga", NAMES), ["denylist name"])
        self.assertEqual(kinds("Rocío vino", NAMES), [])

    def test_single_word_entry_warns_without_its_value(self):
        err = io.StringIO()
        with redirect_stderr(err):
            g.Denylist.parse("Rocío\n")
        self.assertIn("line 1", err.getvalue())
        self.assertNotIn("Roc", err.getvalue())

    def test_surname_first_entry_matches_both_orders(self):
        names = g.Denylist.parse("Quezada Rojas, Bastián\n")
        self.assertEqual(kinds("Bastián Quezada Rojas", names), ["denylist name"])
        self.assertEqual(kinds("QUEZADA ROJAS BASTIAN", names), ["denylist name"])
        self.assertEqual(kinds("Bastián Quezada", names), [])

    def test_short_number_entry_warns_and_is_ignored(self):
        err = io.StringIO()
        with redirect_stderr(err):
            numbers = g.Denylist.parse("1.234.567\n")
        self.assertFalse(numbers)
        self.assertIn("line 1 is under 8 digits", err.getvalue())

    def test_listed_email_and_numbers(self):
        self.assertEqual(kinds("from XIMENA.real@gmail.com", NAMES), ["email", "denylist email"])
        self.assertEqual(kinds("rut 21333444-k", NAMES), ["denylist number"])
        self.assertEqual(
            kinds("fono 977771234", NAMES, where="backend/tests/x.py"), ["denylist number"]
        )


class LocalPath(unittest.TestCase):
    def test_each_absolute_form_is_caught(self):
        for text in [
            "see /Volumes/Disk/gits/app/notes.md",
            "at /Users/alguien/code/x",
            "in /home/alguien/.bashrc",
            "file:///Users/alguien/x.html",
            r"C:\Users\alguien\Desktop",
            r"C:\\Users\\alguien",
            "D:/Users/alguien/x",
            "under ~/Documents/planilla.xlsx",
            "cd ~/gits/otro-proyecto",
            "`~/.claude/projects/x`",
            "~/.config/otra-cosa/x",
        ]:
            with self.subTest(text=text):
                self.assertEqual(kinds(text), ["local-path"])

    def test_relative_paths_and_placeholders_pass(self):
        for text in [
            "edit scripts/pii_guard.py and docs/privacy-guard.md",
            "frontend/src/home/Users/x.tsx",
            "https://github.com/o/r/blob/main/home/Users/x",
            "`/Users/<name>/…`, `/Volumes/…`, `/home/<name>`, `C:\\Users\\…`",
            "~/ alone, and ~ by itself",
            "/srv/rakin and /tmp/x",
        ]:
            with self.subTest(text=text):
                self.assertEqual(kinds(text), [])

    def test_documented_home_locations_pass(self):
        for text in [
            "`~/.config/rakin/pii-denylist.txt`",
            "~/.config/rakin/private-terms.txt",
            "ls ~/.task-force/radio/sessions/",
            "defaults to ~/.task-force.",
            "install -d -m 700 ~/.ssh",
        ]:
            with self.subTest(text=text):
                self.assertEqual(kinds(text), [])

    def test_a_documented_prefix_is_a_whole_segment(self):
        self.assertEqual(kinds("~/.task-forcex/y"), ["local-path"])
        self.assertEqual(kinds("~/.config/rakinx"), ["local-path"])
        self.assertEqual(kinds("~/.task-force/../Documents"), ["local-path"])

    def test_pii_ok_marks_a_path(self):
        self.assertEqual(kinds("/home/deploy/.ssh  # pii-ok: the server's user"), [])


class PrivateTerms(unittest.TestCase):
    TERMS = g.Denylist(terms=g.Denylist.parse_terms("Borealis\nProyecto Tundra\nACM\n# a note\n"))

    def test_whole_word_in_any_case_or_accent(self):
        for text in [
            "the borealis repo",
            "BOREALIS-12 is a ticket",
            "Boreális",
            "borealis_utils",
            "proyecto  tundra",
            "Proyecto-Tundra",
            "ACM-41",
        ]:
            with self.subTest(text=text):
                self.assertEqual(kinds(text, self.TERMS), ["private-term"])

    def test_not_inside_another_word(self):
        for text in ["borealisx", "aborealis", "tundra alone", "acme", "proyecto"]:
            with self.subTest(text=text):
                self.assertEqual(kinds(text, self.TERMS), [])

    def test_pii_ok_and_fixtures_do_not_skip_terms(self):
        self.assertEqual(kinds("borealis # pii-ok", self.TERMS), ["private-term"])
        self.assertEqual(kinds("borealis", self.TERMS, "backend/tests/x.py"), ["private-term"])

    def test_short_term_warns_without_its_value(self):
        err = io.StringIO()
        with redirect_stderr(err):
            terms = g.Denylist.parse_terms("zq\nfine\n")
        self.assertEqual(terms, (("fine",),))
        self.assertIn("line 1", err.getvalue())
        self.assertNotIn("zq", err.getvalue())

    def test_values_are_never_printed(self):
        text = "Proyecto Tundra in /Users/alguien/gits/borealis\n"
        env = {"PRIVATE_TERMS": "Borealis\nProyecto Tundra\n"}
        result = run("scan", "--name", "body", stdin=text, env=env)
        self.assertEqual(result.returncode, 1)
        self.assertIn("body:1:1: private-term", result.stderr)
        self.assertIn("local-path", result.stderr)
        for secret in ("Tundra", "tundra", "borealis", "Borealis", "alguien", "/Users"):
            self.assertNotIn(secret, result.stdout + result.stderr)

    def test_no_denylist_skips_terms(self):
        result = run("--no-denylist", "scan", stdin="borealis\n", env={"PRIVATE_TERMS": "borealis"})
        self.assertEqual(result.returncode, 0)


class Mark(unittest.TestCase):
    def test_pii_ok_skips_patterns(self):
        self.assertEqual(kinds(f"{VALID_RUT}  # pii-ok: invented"), [])

    def test_pii_ok_does_not_skip_the_denylist(self):
        self.assertEqual(kinds("Bastián Quezada  # pii-ok", NAMES), ["denylist name"])

    def test_fixture_paths_skip_patterns_only(self):
        self.assertEqual(kinds(VALID_RUT, where="backend/tests/test_x.py"), [])
        self.assertEqual(kinds(VALID_RUT, where="backend/app/x.py"), ["rut"])
        self.assertEqual(kinds("Bastián Quezada", NAMES, "backend/tests/x.py"), ["denylist name"])


class Diff(unittest.TestCase):
    DIFF = "\n".join(
        [
            "diff --git a/docs/a.md b/docs/a.md",
            "--- a/docs/a.md",
            "+++ b/docs/a.md",
            "@@ -1,0 +10,3 @@",
            f"-old {VALID_RUT}",
            "+fine",
            f"+rut {VALID_RUT}",
            "+Bastián Quezada",
            "diff --git a/backend/tests/t.py b/backend/tests/t.py",
            "+++ b/backend/tests/t.py",
            "@@ -0,0 +1 @@",
            f"+{VALID_RUT}",
        ]
    )

    def test_added_lines_at_their_new_numbers(self):
        hits = g.scan_diff(self.DIFF, NAMES)
        self.assertEqual(
            [str(h) for h in hits], ["docs/a.md:11:5: rut", "docs/a.md:12:1: denylist name"]
        )


class CommitMessage(unittest.TestCase):
    def msg(self, text: str, denylist: str = ""):
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
            f.write(text)
        return run("commit-msg", f.name, env={"PII_DENYLIST": denylist} if denylist else None)

    def test_metadata_lines_skip_the_patterns(self):
        text = (
            "Fix: thing\n\nSigned-off-by: Dev <dev@gmail.com>\n"
            "Co-Authored-By: Claude <noreply@anthropic.com>\n# Author: Dev <dev@gmail.com>\n"
        )
        self.assertEqual(self.msg(text).returncode, 0)

    def test_hash_lines_are_scanned(self):
        # `git commit -m` / `-F` keep `#` lines, so a markdown heading is public.
        result = self.msg("Fix: thing\n\n# Bastián Quezada\n", "Bastián Quezada\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("commit message:3:3: denylist name", result.stderr)
        self.assertEqual(self.msg(f"Fix\n\n# rut {VALID_RUT}\n").returncode, 1)

    def test_scissors_tail_is_skipped(self):
        text = f"Fix\n# ------------------------ >8 ------------------------\n+{VALID_RUT}\n"
        self.assertEqual(self.msg(text).returncode, 0)

    def test_trailers_still_get_the_denylist(self):
        result = self.msg(
            "Fix\n\nReported-by: Bastián Quezada <b@gmail.com>\n", "Bastián Quezada\n"
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("denylist name", result.stderr)
        self.assertNotIn(": email", result.stderr)

    def test_body_is_scanned(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write(f"Fix: thing\n\nfor RUT {VALID_RUT}\n")
        result = run("commit-msg", f.name)
        self.assertEqual(result.returncode, 1)
        self.assertIn("commit message:3:9: rut", result.stderr)


class Output(unittest.TestCase):
    SECRETS = (VALID_RUT, "973124501", "someone@gmail.com", "Bastián", "Quezada", "bastian")

    def test_values_are_never_printed(self):
        denylist = "Bastián Quezada\n"
        text = f"{VALID_RUT} 973124501 someone@gmail.com\nBastián Quezada\n"
        result = run("scan", "--name", "body", stdin=text, env={"PII_DENYLIST": denylist})
        self.assertEqual(result.returncode, 1)
        self.assertIn("body:1:1: rut", result.stderr)
        self.assertIn("body:2:1: denylist name", result.stderr)
        for secret in self.SECRETS:
            self.assertNotIn(secret, result.stdout + result.stderr)

    def test_clean_is_silent(self):
        result = run("scan", stdin="nothing to see\n")
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, "", ""))

    def test_jsonl_records(self):
        records = [
            {"label": "issue#7/body", "text": "ok"},
            {"label": "comment 9", "text": f"x\n{VALID_RUT}"},
        ]
        stdin = "\n".join(json.dumps(r) for r in records)
        result = run("scan", "--jsonl", "-", stdin=stdin)
        self.assertEqual(result.returncode, 1)
        self.assertIn("comment 9:2:1: rut", result.stderr)


class DenylistSource(unittest.TestCase):
    def test_env_content_then_file_then_default(self):
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("Bastián Quezada\n")
        with mock.patch.dict(os.environ, {"PII_DENYLIST": "Ximena Ñúñez Peñaloza"}, clear=False):
            self.assertEqual(g.Denylist.load().source, "$PII_DENYLIST")
        env = {k: v for k, v in os.environ.items() if not k.startswith(LISTS)}
        env.update(NO_LISTS, PII_DENYLIST_FILE=f.name)
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(g.Denylist.load().source, f.name)
        env["PII_DENYLIST_FILE"] = "/nonexistent"
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertFalse(g.Denylist.load())

    def test_private_terms_env_content_then_file(self):
        env = {k: v for k, v in os.environ.items() if not k.startswith(LISTS)}
        env.update(NO_LISTS, PRIVATE_TERMS="Proyecto Borealis\n")
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(g.Denylist.load().terms, (("proyecto", "borealis"),))
        with tempfile.NamedTemporaryFile("w", delete=False) as f:
            f.write("tundra\n")
        del env["PRIVATE_TERMS"]
        env["PRIVATE_TERMS_FILE"] = f.name
        with mock.patch.dict(os.environ, env, clear=True):
            self.assertEqual(g.Denylist.load().terms, (("tundra",),))


class ClaudeHook(unittest.TestCase):
    def hook(self, command: str, cwd: str, denylist: str = "Bastián Quezada\n"):
        payload = {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": cwd}
        env = {"PII_DENYLIST": denylist, "PRIVATE_TERMS": "Borealis\n"}
        return run("claude-hook", stdin=json.dumps(payload), env=env)

    def test_comment_naming_a_private_term_or_a_path_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "c.md").write_text("Same as in the borealis repo.\n")
            result = self.hook("gh issue comment 5 --body-file c.md", d)
            self.assertEqual(result.returncode, 2)
            self.assertIn("c.md:1:16: private-term", result.stderr)
            Path(d, "c.md").write_text("Logs in /Volumes/Disk/gits/x.\n")
            result = self.hook("gh issue comment 5 --body-file c.md", d)
            self.assertEqual(result.returncode, 2)
            self.assertIn("c.md:1:9: local-path", result.stderr)
        for command in [
            "gh issue comment 5 --body 'see ~/Documents/x'",
            "gh issue comment 5 --body-file - <<'B'\nfrom Borealis\nB",
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.hook(command, "/").returncode, 2)

    def test_paths_the_command_only_reads_pass(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "b.md").write_text("All fine.\n")
            for command in [
                f"gh pr create --body-file {d}/b.md",
                f"cd {d} && gh issue comment 5 -F b.md",
                f'cd "{d}"; gh issue create --body "$(cat {d}/b.md)"',
            ]:
                with self.subTest(command=command):
                    result = self.hook(command, d)
                    self.assertEqual(result.returncode, 0, result.stderr)
        text = "cd /Volumes/Disk/x && gh pr create --body-file /Users/alguien/b.md --title ok"
        published = g.published_text(text)
        self.assertNotIn("/Users", published)
        self.assertNotIn("/Volumes", published)
        self.assertIn("--title ok", published)
        self.assertEqual(len(published), len(text))
        self.assertEqual(kinds(published), [])

    def test_paths_inside_a_posted_body_are_still_caught(self):
        for command in [
            "gh issue comment 5 --body-file - <<'B'\nfirst cd /Volumes/Disk/x\nB",
            "gh issue comment 5 --body-file - <<'B'\ncd /Users/alguien/x\nB",
            "gh issue comment 5 --body 'logs at /Users/alguien/x'",
        ]:
            with self.subTest(command=command):
                self.assertEqual(self.hook(command, "/").returncode, 2)

    def test_body_file_with_a_denylisted_name_is_blocked(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "body.md").write_text("Reported by Bastián Quezada\n")
            result = self.hook("gh issue create --title Bug --body-file body.md", d)
            self.assertEqual(result.returncode, 2)
            self.assertIn("body.md:1:13: denylist name", result.stderr)
            self.assertNotIn("Quezada", result.stderr)

    def test_other_file_flags(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "b.json").write_text(f'{{"body": "{VALID_RUT}"}}\n')
            Path(d, "c.md").write_text("973124501\n")
            for command in [
                "gh api repos/o/r/issues --input b.json",
                "gh api repos/o/r/issues -F body=@c.md",
                "gh pr comment 3 -F 'c.md'",
                "cd x && gh release create v1 --notes-file c.md",
            ]:
                with self.subTest(command=command):
                    self.assertEqual(self.hook(command, d).returncode, 2)

    def test_heredoc_body_in_the_command(self):
        command = "gh pr create --body-file - <<'BODY'\n## Summary\nFor bastian quezada.\nBODY"
        self.assertEqual(self.hook(command, "/").returncode, 2)

    def test_body_read_through_cat_is_scanned(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "b.md").write_text("Bastián Quezada\n")
            for command in [
                'gh issue create --body "$(cat b.md)"',
                'gh pr comment 1 -b "$(<b.md)"',
            ]:
                with self.subTest(command=command):
                    self.assertEqual(self.hook(command, d).returncode, 2)

    def test_unresolvable_body_file_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            for command in [
                "gh issue create --body-file $PII_TEST_UNSET_VAR/b.md",
                "gh issue create --body-file $(mktemp)",
                "gh issue create --body-file missing.md",
            ]:
                with self.subTest(command=command):
                    result = self.hook(command, d)
                    self.assertEqual(result.returncode, 2)
                    self.assertIn("unreadable body file", result.stderr)

    def test_variables_in_body_file_paths_are_expanded(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "b.md").write_text("Bastián Quezada\n")
            payload = {
                "tool_name": "Bash",
                "tool_input": {"command": "gh issue create --body-file $BODY_DIR/b.md"},
            }
            env = {"PII_DENYLIST": "Bastián Quezada\n", "BODY_DIR": d}
            result = run("claude-hook", stdin=json.dumps(payload), env=env)
            self.assertEqual(result.returncode, 2)
            self.assertIn("denylist name", result.stderr)

    def test_clean_and_unrelated_calls_pass(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d, "body.md").write_text("All fine.\n")
            self.assertEqual(self.hook("gh issue create --body-file body.md", d).returncode, 0)
            self.assertEqual(self.hook(f"echo {VALID_RUT}", d).returncode, 0)
            payload = {"tool_name": "Read", "tool_input": {"file_path": "x"}}
            self.assertEqual(run("claude-hook", stdin=json.dumps(payload)).returncode, 0)


class GitHooks(unittest.TestCase):
    """`make hooks` in a scratch repo: refuses locally, chains what was there."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Path(self.tmp.name)
        root = SCRIPT.parent
        (self.repo / "scripts").mkdir()
        for name in ("pii_guard.py", "install-hooks.sh"):
            (self.repo / "scripts" / name).write_bytes((root / name).read_bytes())
        self.git("init", "-q")
        self.git("config", "user.name", "Dev")
        self.git("config", "user.email", "dev@example.com")
        self.git("config", "commit.gpgsign", "false")
        self.git("config", "core.hooksPath", ".git/hooks")
        hooks = self.repo / ".git" / "hooks"
        hooks.mkdir(exist_ok=True)
        prior = hooks / "commit-msg"
        prior.write_text('#!/bin/sh\necho prior >> "$(git rev-parse --git-dir)/chained"\n')
        prior.chmod(0o755)
        self.env = {**os.environ, **NO_LISTS, "PII_DENYLIST": "Bastián Quezada\n"}
        self.env.pop("PRIVATE_TERMS", None)
        subprocess.run(
            ["bash", "scripts/install-hooks.sh"], cwd=self.repo, check=True, capture_output=True
        )

    def tearDown(self):
        self.tmp.cleanup()

    def git(self, *args: str, check: bool = True):
        return subprocess.run(
            ["git", *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=check,
            env=getattr(self, "env", None),
        )

    def commit(self, content: str, message: str = "Add notes"):
        (self.repo / "notes.md").write_text(content)
        self.git("add", "notes.md")
        return self.git("commit", "-q", "-m", message, check=False)

    def test_clean_commit_passes_and_chains_the_prior_hook(self):
        self.assertEqual(self.commit("hello\n").returncode, 0)
        self.assertTrue((self.repo / ".git" / "chained").exists())

    def test_denylisted_name_is_refused(self):
        result = self.commit("Bastián Quezada pagó\n")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("notes.md:1:1: denylist name", result.stderr)

    def test_valid_rut_is_refused(self):
        self.assertNotEqual(self.commit(f"rut {VALID_RUT}\n").returncode, 0)

    def test_message_is_scanned(self):
        self.assertNotEqual(self.commit("ok\n", f"Add notes for {VALID_RUT}").returncode, 0)

    def test_install_is_idempotent(self):
        result = subprocess.run(
            ["bash", "scripts/install-hooks.sh"], cwd=self.repo, capture_output=True, text=True
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.commit("hello\n").returncode, 0)
        self.assertEqual((self.repo / ".git" / "chained").read_text(), "prior\n")


if __name__ == "__main__":
    unittest.main()
