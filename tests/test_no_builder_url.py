import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class NoBuilderUrlTest(unittest.TestCase):
    def test_cli_source_does_not_configure_builder_directly(self):
        forbidden = [
            "127.0.0.1:" + "8001",
            "builder" + "_url",
            "BUILD" + "ER_URL",
            "BUILD" + "ER_API",
            "ai." + "basebuilder.cn",
        ]
        checked = []
        for path in [ROOT / "src", ROOT / "tests", ROOT / "README.md", ROOT / "skills"]:
            if path.is_dir():
                files = [p for p in path.rglob("*") if p.is_file()]
            elif path.exists():
                files = [path]
            else:
                files = []
            scanner_name = "test_no_" + "builder" + "_url.py"
            checked.extend(file for file in files if file.name != scanner_name)

        matches = []
        for file in checked:
            if file.suffix in {".py", ".md", ".toml"}:
                text = file.read_text(errors="ignore")
                for item in forbidden:
                    if item in text:
                        matches.append(f"{file.relative_to(ROOT)} contains {item}")

        self.assertEqual(matches, [])


if __name__ == "__main__":
    unittest.main()
