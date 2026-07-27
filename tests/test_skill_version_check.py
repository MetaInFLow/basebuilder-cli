from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE_SKILL = ROOT / "skills" / "basebuilder-cli"
PACKAGED_SKILL = ROOT / "src" / "basebuilder_cli" / "resources" / "basebuilder-cli"
SCRIPT_PATH = SOURCE_SKILL / "scripts" / "check_version.py"


def load_checker():
    spec = importlib.util.spec_from_file_location("basebuilder_skill_version_checker", SCRIPT_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SkillVersionCheckTest(unittest.TestCase):
    def test_both_skills_require_version_check_as_first_action(self):
        for skill_dir in (SOURCE_SKILL, PACKAGED_SKILL):
            content = (skill_dir / "SKILL.md").read_text()
            self.assertIn("Version Check First", content)
            self.assertIn("scripts/check_version.py", content)
            self.assertTrue((skill_dir / "scripts" / "check_version.py").exists())

    def test_source_and_packaged_checkers_match(self):
        self.assertEqual(
            (SOURCE_SKILL / "scripts" / "check_version.py").read_text(),
            (PACKAGED_SKILL / "scripts" / "check_version.py").read_text(),
        )

    def test_checker_classifies_commit_state(self):
        checker = load_checker()
        self.assertEqual(checker.classify("abc", "abc", editable=False), "up_to_date")
        self.assertEqual(checker.classify("abc", "def", editable=False), "update_available")
        self.assertEqual(checker.classify("abc", "def", editable=True), "editable_source_differs")
        self.assertEqual(checker.classify("", "def", editable=False), "unknown")

    def test_checker_selects_latest_stable_release_tag(self):
        checker = load_checker()
        tags = "\n".join([
            "aaaaaaaa refs/tags/v0.1.0",
            "bbbbbbbb refs/tags/v0.2.0",
            "cccccccc refs/tags/v0.2.0^{}",
            "dddddddd refs/tags/v0.3.0rc1",
        ])

        self.assertEqual(checker.parse_release_tags(tags), {
            "version": "0.2.0",
            "tag": "v0.2.0",
            "commit": "cccccccc",
        })

    def test_checker_classifies_release_versions(self):
        checker = load_checker()
        self.assertEqual(checker.classify_version("0.1.0", "0.2.0"), "update_available")
        self.assertEqual(checker.classify_version("0.2.0", "0.2.0"), "up_to_date")
        self.assertEqual(checker.classify_version("0.3.0", "0.2.0"), "ahead_of_release")
        self.assertEqual(checker.classify_version("dev", "0.2.0"), "unknown")

    def test_checker_uses_release_channel_only_for_stable_installs(self):
        checker = load_checker()
        self.assertTrue(checker.uses_release_channel({
            "requested_revision": "v0.2.0",
            "editable": False,
        }))
        self.assertFalse(checker.uses_release_channel({
            "requested_revision": "main",
            "editable": False,
        }))
        self.assertFalse(checker.uses_release_channel({
            "requested_revision": "v0.2.0",
            "editable": True,
        }))

    def test_checker_preserves_requested_revision(self):
        checker = load_checker()
        source = checker.local_source_info({
            "direct_url": {
                "url": "https://github.com/MetaInFLow/basebuilder-cli.git",
                "vcs_info": {
                    "commit_id": "abc123",
                    "requested_revision": "v0.2.0",
                },
            },
        })

        self.assertEqual(source["requested_revision"], "v0.2.0")


if __name__ == "__main__":
    unittest.main()
