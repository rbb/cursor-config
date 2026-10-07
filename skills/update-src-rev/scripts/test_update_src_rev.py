#!/usr/bin/env python3
"""Regression coverage for update-src-rev recipe consumer discovery."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import update_src_rev as update


class RecipeConsumerDiscovery(unittest.TestCase):
    """Keep URI-to-SRCREV matching local to update-src-rev."""

    def test_discovers_optional_and_definitive_consumers_in_layers(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-src-rev-") as raw:
            root = Path(raw)
            workspace = root / "work"
            old = "a" * 40
            target = "b" * 40
            layers: list[Path] = []
            for layer_name, operator in (
                ("meta-judo", "="),
                ("meta-judo-proprietary", "?="),
            ):
                layer = workspace / "oe" / layer_name
                recipe = layer / "recipes-test" / "foo.bb"
                recipe.parent.mkdir(parents=True)
                recipe.write_text(
                    'SRC_URI = "git://${TOPDIR}/../src/foo;protocol=file"\n'
                    f'SRCREV {operator} "{old}"\n',
                    encoding="utf-8",
                )
                layers.append(layer)

            pins = update.stale_recipe_pins(
                layers, "foo", workspace, target
            )

            self.assertEqual(len(pins), 2)
            self.assertEqual(
                sorted(pin.definite for pin in pins), [False, True]
            )

    def test_named_uri_selects_its_matching_srcrev_only(self) -> None:
        content = (
            'SRC_URI = "git://${TOPDIR}/../src/foo;protocol=file;name=foo"\n'
            f'SRCREV = "{"a" * 40}"\n'
            f'SRCREV_foo = "{"b" * 40}"\n'
        )
        self.assertEqual(
            update.find_srcrev_targets(content, "foo"), ["SRCREV_foo"]
        )

    def test_detects_colon_override_without_guessing_it(self) -> None:
        with tempfile.TemporaryDirectory(prefix="update-src-rev-") as raw:
            workspace = Path(raw) / "work"
            layer = workspace / "oe" / "meta-judo"
            recipe = layer / "recipes-test" / "foo.bb"
            recipe.parent.mkdir(parents=True)
            recipe.write_text(
                'SRC_URI = "git://${TOPDIR}/../src/foo;protocol=file"\n'
                f'SRCREV:machine = "{"a" * 40}"\n',
                encoding="utf-8",
            )
            self.assertEqual(
                update.unresolved_override_recipes(
                    [layer], "foo", workspace
                ),
                ["oe/meta-judo/recipes-test/foo.bb"],
            )


if __name__ == "__main__":
    unittest.main()
