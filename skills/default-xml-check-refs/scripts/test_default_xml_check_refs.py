#!/usr/bin/env python3
"""Regression: ref checks must not shallow the project checkout."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

import default_xml_check_refs as check


def git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


class CheckRefsDoesNotShallow(unittest.TestCase):
    def test_full_clone_stays_full(self) -> None:
        with tempfile.TemporaryDirectory(prefix="check-refs-") as raw:
            root = Path(raw)
            remote = root / "proj.git"
            src = root / "src"
            work = root / "work"
            checkout = work / "proj"

            git(root, "init", "--bare", "-b", "main", str(remote))
            git(root, "init", "-b", "main", str(src))
            git(src, "config", "user.email", "t@example.com")
            git(src, "config", "user.name", "test")
            (src / "f").write_text("one\n", encoding="utf-8")
            git(src, "add", "f")
            git(src, "commit", "-m", "one")
            (src / "f").write_text("two\n", encoding="utf-8")
            git(src, "commit", "-am", "two")
            sha = git(src, "rev-parse", "HEAD")
            git(src, "remote", "add", "origin", str(remote))
            git(src, "push", "origin", "main")

            git(root, "clone", str(remote), str(checkout))
            git(root, "init", "-b", "main", str(work))
            manifest = work / "default.xml"
            manifest.write_text(
                "<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n"
                "<manifest>\n"
                f"  <remote name=\"origin\" fetch=\"{root}\"/>\n"
                "  <project name=\"proj\" path=\"proj\" remote=\"origin\" "
                f"revision=\"{sha}\"/>\n"
                "</manifest>\n",
                encoding="utf-8",
            )

            code = check.main(
                ["-w", str(work), "-m", str(manifest), "-q"]
            )
            self.assertEqual(code, 0)
            self.assertEqual(
                git(checkout, "rev-parse", "--is-shallow-repository"),
                "false",
            )
            self.assertFalse((checkout / ".git" / "shallow").exists())
            parents = git(checkout, "rev-list", "--parents", "-n", "1", "HEAD")
            self.assertEqual(len(parents.split()), 2)


if __name__ == "__main__":
    unittest.main()
