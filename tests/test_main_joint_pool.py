import json
import tempfile
import unittest
from pathlib import Path

import main


class CollectPoolIdsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.original_table_dir = main.TABLE_DIR
        main.TABLE_DIR = self.root / "TableCfg"
        main.TABLE_DIR.mkdir(parents=True)

        char_table = {
            "special_pool": {"type": "Special"},
            "joint_pool": {"type": "Joint"},
            "normal_pool": {"type": "Normal"},
        }
        weapon_table = {
            "weapon_pool": {"type": "weapon"},
        }

        (main.TABLE_DIR / "GachaCharPoolTable.json").write_text(
            json.dumps(char_table, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        (main.TABLE_DIR / "GachaWeaponPoolTable.json").write_text(
            json.dumps(weapon_table, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def tearDown(self):
        main.TABLE_DIR = self.original_table_dir
        self.tmp.cleanup()

    def test_collect_pool_ids_includes_joint_character_pools(self):
        self.assertEqual(
            main.collect_pool_ids(),
            ["special_pool", "joint_pool", "weapon_pool"],
        )


if __name__ == "__main__":
    unittest.main()
