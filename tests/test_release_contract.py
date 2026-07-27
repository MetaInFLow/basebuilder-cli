from __future__ import annotations

import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReleaseContractTest(unittest.TestCase):
    def test_v020_has_one_version_source(self):
        pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text())

        self.assertNotIn("version", pyproject["project"])
        self.assertIn("version", pyproject["project"]["dynamic"])
        self.assertEqual(
            pyproject["tool"]["setuptools"]["dynamic"]["version"]["attr"],
            "basebuilder_cli.__version__",
        )
        self.assertIn(
            '__version__ = "0.2.0"',
            (ROOT / "src" / "basebuilder_cli" / "__init__.py").read_text(),
        )

    def test_stable_installation_is_pinned_to_v020(self):
        readme = (ROOT / "README.md").read_text()
        source_skill = (ROOT / "skills" / "basebuilder-cli" / "SKILL.md").read_text()

        self.assertIn("basebuilder-cli.git@v0.2.0", readme)
        self.assertIn("basebuilder-cli.git@v0.2.0", source_skill)
        self.assertIn("GitHub main", readme)


if __name__ == "__main__":
    unittest.main()
