import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from basebuilder_cli.artifacts import write_manual, write_skill


SAMPLE_ARTIFACT = {
    "base": {
        "name": "跨境电商SKU进销存ERP",
        "url": "https://metainflow.feishu.cn/base/sample",
    },
    "summary": {
        "tables": 2,
        "fields": 5,
        "views": 3,
    },
    "tables": [
        {
            "name": "SKU建档",
            "description": "维护商品主数据",
            "fields": [
                {"name": "SKU编码", "type": "text", "description": "唯一商品编码"},
                {"name": "状态", "type": "single_select", "description": "上架状态"},
            ],
            "views": [{"name": "在售SKU", "type": "grid"}],
        },
        {
            "name": "库存归集",
            "description": "按仓库汇总库存",
            "fields": [
                {"name": "仓库", "type": "text", "description": "仓库名称"},
                {"name": "可售库存", "type": "number", "description": "可销售数量"},
                {"name": "SKU", "type": "link", "description": "关联 SKU建档"},
            ],
            "views": [{"name": "低库存预警", "type": "kanban"}],
        },
    ],
    "workflow": ["录入SKU", "同步库存", "查看预警"],
}


class ArtifactsTest(unittest.TestCase):
    def test_manual_and_skill_are_specific_and_secret_free(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            manual = write_manual(SAMPLE_ARTIFACT, root / "manual.md")
            skill_dir = write_skill(SAMPLE_ARTIFACT, root / "skill")

            manual_text = manual.read_text()
            skill_text = (skill_dir / "SKILL.md").read_text()
            schema = json.loads((skill_dir / "references" / "base-schema.json").read_text())

        self.assertIn("跨境电商SKU进销存ERP", manual_text)
        self.assertTrue(skill_text.startswith("---\nname: "))
        self.assertIn("description: Use when", skill_text)
        self.assertIn("SKU建档", manual_text)
        self.assertIn("低库存预警", manual_text)
        self.assertIn("跨境电商SKU进销存ERP", skill_text)
        self.assertIn("SKU编码", skill_text)
        self.assertIn("低库存预警", skill_text)
        self.assertIn("高风险写入", skill_text)
        self.assertEqual(schema["base"]["name"], "跨境电商SKU进销存ERP")

        combined = manual_text + skill_text + json.dumps(schema, ensure_ascii=False)
        for forbidden in ["token", "cookie", "secret", "apiclient_key", "authorization", "raw prompt"]:
            self.assertNotIn(forbidden, combined.lower())

    def test_manual_treats_workflow_string_as_one_step(self):
        artifact = dict(SAMPLE_ARTIFACT)
        artifact["workflow"] = "录入SKU -> 同步库存 -> 查看预警"

        with tempfile.TemporaryDirectory() as tmp:
            manual = write_manual(artifact, Path(tmp) / "manual.md")
            manual_text = manual.read_text()

        self.assertIn("1. 录入SKU -> 同步库存 -> 查看预警", manual_text)
        self.assertNotIn("2. 入", manual_text)


if __name__ == "__main__":
    unittest.main()
