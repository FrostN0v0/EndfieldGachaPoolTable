import json
import unittest
import tempfile
from pathlib import Path

import sync_tablecfg


class FakeResponse:
    def __init__(self, status_code=200, headers=None, content=b"{}"):
        self.status_code = status_code
        self.headers = headers or {}
        self.content = content


class FakeClient:
    def __init__(self, head_responses, get_responses):
        self.head_responses = head_responses
        self.get_responses = get_responses
        self.head_calls = []
        self.get_calls = []

    def head(self, url, **kwargs):
        self.head_calls.append((url, kwargs))
        response = self.head_responses[url]
        if isinstance(response, Exception):
            raise response
        return response

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        response = self.get_responses[url]
        if isinstance(response, Exception):
            raise response
        return response


class SyncTableCfgTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.original_table_dir = sync_tablecfg.TABLE_DIR
        self.original_state_path = sync_tablecfg.STATE_PATH
        sync_tablecfg.TABLE_DIR = self.root / "TableCfg"
        sync_tablecfg.STATE_PATH = self.root / ".github" / "tablecfg-sync-state.json"
        sync_tablecfg.TABLE_DIR.mkdir(parents=True)
        sync_tablecfg.STATE_PATH.parent.mkdir(parents=True)

    def tearDown(self):
        sync_tablecfg.TABLE_DIR = self.original_table_dir
        sync_tablecfg.STATE_PATH = self.original_state_path
        self.tmp.cleanup()

    def url_for(self, filename):
        return f"{sync_tablecfg.REMOTE_BASE_URL}/{filename}"

    def metadata_for(self, filename):
        return {
            "last_modified": f"Thu, 14 May 2026 02:46:{len(filename):02d} GMT",
            "etag": f'"etag-{filename}"',
            "content_length": str(1000 + len(filename)),
        }

    def headers_for(self, filename):
        metadata = self.metadata_for(filename)
        return {
            "last-modified": metadata["last_modified"],
            "etag": metadata["etag"],
            "content-length": metadata["content_length"],
        }

    def write_state(self):
        state = {filename: self.metadata_for(filename) for filename in sync_tablecfg.TABLE_FILES}
        sync_tablecfg.STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state

    def fake_head_responses(self):
        return {
            self.url_for(filename): FakeResponse(headers=self.headers_for(filename))
            for filename in sync_tablecfg.TABLE_FILES
        }

    def test_cache_hit_skips_download(self):
        self.write_state()
        for filename in sync_tablecfg.TABLE_FILES:
            (sync_tablecfg.TABLE_DIR / filename).write_text(f'{{"local":"{filename}"}}', encoding="utf-8")

        client = FakeClient(self.fake_head_responses(), {})

        changed = sync_tablecfg.sync_tablecfg(client)

        self.assertFalse(changed)
        self.assertEqual([], client.get_calls)
        for filename in sync_tablecfg.TABLE_FILES:
            self.assertEqual(
                f'{{"local":"{filename}"}}',
                (sync_tablecfg.TABLE_DIR / filename).read_text(encoding="utf-8"),
            )

    def test_changed_remote_replaces_files_and_updates_state(self):
        for filename in sync_tablecfg.TABLE_FILES:
            (sync_tablecfg.TABLE_DIR / filename).write_text('{"old":true}', encoding="utf-8")

        get_responses = {
            self.url_for(filename): FakeResponse(content=f'{{"remote":"{filename}"}}'.encode("utf-8"))
            for filename in sync_tablecfg.TABLE_FILES
        }
        client = FakeClient(self.fake_head_responses(), get_responses)

        changed = sync_tablecfg.sync_tablecfg(client)

        self.assertTrue(changed)
        for filename in sync_tablecfg.TABLE_FILES:
            self.assertEqual(
                f'{{"remote":"{filename}"}}',
                (sync_tablecfg.TABLE_DIR / filename).read_text(encoding="utf-8"),
            )
        state = json.loads(sync_tablecfg.STATE_PATH.read_text(encoding="utf-8"))
        self.assertEqual({filename: self.metadata_for(filename) for filename in sync_tablecfg.TABLE_FILES}, state)

    def test_invalid_json_preserves_all_files_and_state(self):
        first_file, second_file = sync_tablecfg.TABLE_FILES
        for filename in sync_tablecfg.TABLE_FILES:
            (sync_tablecfg.TABLE_DIR / filename).write_text(f'{{"old":"{filename}"}}', encoding="utf-8")

        get_responses = {
            self.url_for(first_file): FakeResponse(content=b'{"new":true}'),
            self.url_for(second_file): FakeResponse(content=b'not json'),
        }
        client = FakeClient(self.fake_head_responses(), get_responses)

        with self.assertRaises(sync_tablecfg.RemoteFileError):
            sync_tablecfg.sync_tablecfg(client)

        for filename in sync_tablecfg.TABLE_FILES:
            self.assertEqual(
                f'{{"old":"{filename}"}}',
                (sync_tablecfg.TABLE_DIR / filename).read_text(encoding="utf-8"),
            )
        self.assertFalse(sync_tablecfg.STATE_PATH.exists())

    def test_http_failure_preserves_files_and_state(self):
        for filename in sync_tablecfg.TABLE_FILES:
            (sync_tablecfg.TABLE_DIR / filename).write_text(f'{{"old":"{filename}"}}', encoding="utf-8")

        head_responses = self.fake_head_responses()
        head_responses[self.url_for(sync_tablecfg.TABLE_FILES[0])] = FakeResponse(status_code=500)
        client = FakeClient(head_responses, {})

        with self.assertRaises(sync_tablecfg.RemoteFileError):
            sync_tablecfg.sync_tablecfg(client)

        for filename in sync_tablecfg.TABLE_FILES:
            self.assertEqual(
                f'{{"old":"{filename}"}}',
                (sync_tablecfg.TABLE_DIR / filename).read_text(encoding="utf-8"),
            )
        self.assertFalse(sync_tablecfg.STATE_PATH.exists())


if __name__ == "__main__":
    unittest.main()
