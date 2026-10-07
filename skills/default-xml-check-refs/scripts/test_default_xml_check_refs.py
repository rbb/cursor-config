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


class RecipeManifestAlignment(unittest.TestCase):
    def recipe_result(
        self,
        content: str,
        manifest_sha: str = "a" * 40,
    ) -> check.RecipeAlignResult:
        with tempfile.TemporaryDirectory(prefix="recipe-align-") as raw:
            root = Path(raw)
            work = root / "work"
            recipe = work / "oe" / "meta-judo" / "recipes" / "foo.bb"
            recipe.parent.mkdir(parents=True)
            recipe.write_text(content, encoding="utf-8")
            pins = check.discover_recipe_srcrev_pins(
                [recipe.parents[2]], "foo", work
            )
            self.assertEqual(len(pins), 1)
            project = check.ProjectPin(
                "foo", "src/foo", "judo", manifest_sha
            )
            return check.check_recipe_manifest_alignment(
                project, pins[0], work
            )

    def test_mismatch_fails(self) -> None:
        with tempfile.TemporaryDirectory(prefix="recipe-align-") as raw:
            root = Path(raw)
            work = root / "work"
            layer = work / "oe" / "meta-judo-proprietary"
            recipe_dir = layer / "recipes-python" / "python3-foo"
            recipe_dir.mkdir(parents=True)
            manifest_sha = "a" * 40
            recipe_sha = "b" * 40
            (recipe_dir / "python3-foo_git.bb").write_text(
                'SRCREV = "' + recipe_sha + '"\n'
                'SRC_URI = "git://${TOPDIR}/../src/foo;protocol=file"\n',
                encoding="utf-8",
            )
            manifest = work / "default.xml"
            manifest.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                f'  <remote name="judo" fetch="{root}"/>\n'
                '  <project name="meta-judo-proprietary" '
                'path="oe/meta-judo-proprietary" remote="judo" '
                f'revision="{"c" * 40}"/>\n'
                '  <project name="foo" path="src/foo" remote="judo" '
                f'revision="{manifest_sha}"/>\n'
                "</manifest>\n",
                encoding="utf-8",
            )
            results = check.check_all_recipe_alignments(
                work, manifest, [
                    check.ProjectPin(
                        name="foo",
                        path="src/foo",
                        remote_name="judo",
                        revision=manifest_sha,
                    )
                ],
            )
            self.assertEqual(len(results), 1)
            self.assertFalse(results[0].ok)
            self.assertEqual(results[0].status, "mismatch")

    def test_match_ok_without_checkout(self) -> None:
        with tempfile.TemporaryDirectory(prefix="recipe-align-") as raw:
            root = Path(raw)
            work = root / "work"
            layer = work / "oe" / "meta-judo"
            recipe_dir = layer / "recipes" / "bar"
            recipe_dir.mkdir(parents=True)
            sha = "d" * 40
            (recipe_dir / "bar_git.bb").write_text(
                f'SRCREV = "{sha}"\n'
                'SRC_URI = "git://${TOPDIR}/../src/bar;protocol=file"\n',
                encoding="utf-8",
            )
            manifest = work / "default.xml"
            manifest.write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                "<manifest>\n"
                f'  <remote name="judo" fetch="{root}"/>\n'
                '  <project name="meta-judo" path="oe/meta-judo" '
                f'remote="judo" revision="{"e" * 40}"/>\n'
                '  <project name="bar" path="src/bar" remote="judo" '
                f'revision="{sha}"/>\n'
                "</manifest>\n",
                encoding="utf-8",
            )
            results = check.check_all_recipe_alignments(
                work,
                manifest,
                [
                    check.ProjectPin(
                        name="bar",
                        path="src/bar",
                        remote_name="judo",
                        revision=sha,
                    )
                ],
            )
            self.assertEqual(len(results), 1)
            self.assertTrue(results[0].ok)

    def test_optional_srcrev_stale_fails_by_default(self) -> None:
        result = self.recipe_result(
            'SRC_URI = "git://${TOPDIR}/../src/foo;protocol=file"\n'
            f'SRCREV ?= "{"b" * 40}"\n'
        )
        self.assertEqual(result.status, "optional_srcrev_stale")
        self.assertEqual(
            check.recipe_alignment_failures([result], False), [result]
        )
        self.assertEqual(check.recipe_alignment_failures([result], True), [])

    def test_named_uri_ignores_unrelated_srcrev(self) -> None:
        sha = "a" * 40
        result = self.recipe_result(
            'SRC_URI = "git://${TOPDIR}/../src/foo;protocol=file;name=foo"\n'
            f'SRCREV = "{"b" * 40}"\n'
            f'SRCREV_foo = "{sha}"\n',
            sha,
        )
        self.assertTrue(result.ok)

    def test_colon_override_is_reported_as_unresolved(self) -> None:
        result = self.recipe_result(
            'SRC_URI = "git://${TOPDIR}/../src/foo;protocol=file"\n'
            f'SRCREV:machine = "{"a" * 40}"\n'
        )
        self.assertEqual(result.status, "override_srcrev_unresolved")

    def test_multiple_layers_and_mixed_operators_are_discovered(self) -> None:
        with tempfile.TemporaryDirectory(prefix="recipe-align-") as raw:
            work = Path(raw) / "work"
            sha = "a" * 40
            for layer, operator in (
                ("meta-judo", "="),
                ("meta-judo-proprietary", "?="),
            ):
                recipe = work / "oe" / layer / "recipes" / "foo.bb"
                recipe.parent.mkdir(parents=True)
                recipe.write_text(
                    'SRC_URI = "git://${TOPDIR}/../src/foo;protocol=file"\n'
                    f'SRCREV {operator} "{sha}"\n',
                    encoding="utf-8",
                )
            pins = check.discover_recipe_srcrev_pins(
                sorted((work / "oe").glob("meta-judo*")), "foo", work
            )
            self.assertEqual(
                [(pin.operator, pin.srcrev) for pin in pins],
                [("=", sha), ("?=", sha)],
            )


if __name__ == "__main__":
    unittest.main()
