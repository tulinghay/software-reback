"""软件包目录：把「注册表里的显示名」映射到可下载的地址或 winget 包 ID。"""
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from software_reback.catalog import find_entry, load_catalog


CATALOG = {
    "entries": [
        {
            "display_name": "7-Zip 24.08 (x64)",
            "url": "https://example.com/7z2408-x64.msi",
            "file_name": "7z2408-x64.msi",
            "sha256": "a" * 64,
            "silent_args": "/qn",
        },
        {
            "display_name": "Notepad++",
            "winget_id": "Notepad++.Notepad++",
        },
        {
            "display_name": "",
        },
    ]
}


class LoadCatalogTest(unittest.TestCase):
    def test_indexes_entries_by_normalized_display_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "catalog.json"
            path.write_text(json.dumps(CATALOG), encoding="utf-8")
            catalog = load_catalog(path)

        self.assertIn("7-zip 24.08 (x64)", catalog)
        self.assertIn("notepad++", catalog)

    def test_skips_entries_without_display_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "catalog.json"
            path.write_text(json.dumps(CATALOG), encoding="utf-8")
            catalog = load_catalog(path)

        self.assertEqual(len(catalog), 2)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_catalog("不存在.json")

    def test_find_entry_matches_ignoring_case_and_spaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "catalog.json"
            path.write_text(json.dumps(CATALOG), encoding="utf-8")
            catalog = load_catalog(path)

        entry = find_entry(catalog, "  7-zip  24.08 (X64) ")
        self.assertEqual(entry.file_name, "7z2408-x64.msi")

    def test_find_entry_returns_none_when_absent(self):
        self.assertIsNone(find_entry({}, "任意软件"))


if __name__ == "__main__":
    unittest.main()
