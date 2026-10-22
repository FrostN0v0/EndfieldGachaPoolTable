import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import httpx

import main


class CollectPoolIdsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.original_table_dir = main.TABLE_DIR
        main.TABLE_DIR = self.root / "TableCfg"
        main.TABLE_DIR.mkdir(parents=True)

        char_table = {
            "special_pool": {"type": "0"},
            "joint_pool": {"type": "3"},
            "rerun_pool": {"type": "4"},
            "special_numeric": {"type": 0},
            "joint_numeric": {"type": 3},
            "rerun_numeric": {"type": 4},
            "special_named": {"type": "Special"},
            "joint_named": {"type": "Joint"},
            "rerun_named": {"type": "Rerun"},
            "beginner_pool": {"type": "1"},
            "standard_pool": {"type": "2"},
            "beginner_numeric": {"type": 1},
            "standard_numeric": {"type": 2},
            "beginner_named": {"type": "Beginner"},
            "standard_named": {"type": "Standard"},
        }
        weapon_table = {
            "weapon_pool": {"type": "weapon"},
            "rerun_wpn_pool": {"type": "1"},
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

    def test_collect_pool_ids_includes_supported_character_pool_types(self):
        assert set(main.collect_pool_ids()) == {
            "special_pool",
            "joint_pool",
            "rerun_pool",
            "special_numeric",
            "joint_numeric",
            "rerun_numeric",
            "special_named",
            "joint_named",
            "rerun_named",
            "weapon_pool",
            "rerun_wpn_pool",
        }


class FetchPoolContentTests(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_or_empty_response_preserves_archived_rerun(self):
        with tempfile.TemporaryDirectory() as directory:
            base_dir = Path(directory)
            raw_dir = base_dir / "raw"
            raw_dir.mkdir()
            pool_id = "rerun_chr_yvonne"
            pool = {
                "pool_gacha_type": "char",
                "pool_name": "绚丽异彩",
                "pool_type": "rerun",
                "version_num": "1",
            }
            archive = json.dumps({"code": 0, "data": {"pool": pool}}, ensure_ascii=False).encode("utf-8")
            raw_path = raw_dir / f"{pool_id}.json"
            raw_path.write_bytes(archive)
            responses = [
                {"code": 40402, "msg": "Pool not found", "data": {}},
                {"code": 0, "msg": "", "data": {}},
            ]

            with mock.patch.multiple(main, BASE_DIR=base_dir, RAW_DIR=raw_dir):
                for response_data in responses:
                    with self.subTest(code=response_data["code"]):
                        transport = httpx.MockTransport(lambda request: httpx.Response(200, json=response_data))
                        async with httpx.AsyncClient(transport=transport) as client:
                            await main.get_ef_gacha_content(client, pool_id, asyncio.Semaphore(1))

                        assert raw_path.read_bytes() == archive
                        assert main.merge_raw_to_gacha_pool_table()[pool_id] == pool


if __name__ == "__main__":
    unittest.main()
