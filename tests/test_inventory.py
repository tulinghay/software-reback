"""功能 1：读取软件信息 —— 注册表条目归一化与去重。"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from software_reback.inventory import (
    collect,
    merge_records,
    normalize_name,
    record_from_entry,
)
from software_reback.models import SoftwareRecord


class RecordFromEntryTest(unittest.TestCase):
    def test_returns_none_when_display_name_missing(self):
        self.assertIsNone(record_from_entry({"DisplayVersion": "1.0"}))

    def test_returns_none_when_display_name_blank(self):
        self.assertIsNone(record_from_entry({"DisplayName": "   "}))

    def test_skips_system_component_entries(self):
        entry = {"DisplayName": "Windows Driver Package", "SystemComponent": 1}
        self.assertIsNone(record_from_entry(entry))

    def test_skips_patch_and_child_entries(self):
        entry = {"DisplayName": "Update for Foo", "ParentKeyName": "Foo"}
        self.assertIsNone(record_from_entry(entry))

    def test_maps_fields_into_record(self):
        entry = {
            "DisplayName": " 7-Zip 24.08 (x64) ",
            "DisplayVersion": "24.08",
            "Publisher": "Igor Pavlov",
            "InstallLocation": "C:\\Program Files\\7-Zip\\",
        }
        record = record_from_entry(entry)
        self.assertEqual(record.name, "7-Zip 24.08 (x64)")
        self.assertEqual(record.version, "24.08")
        self.assertEqual(record.publisher, "Igor Pavlov")
        self.assertEqual(record.install_location, "C:\\Program Files\\7-Zip\\")
        self.assertEqual(record.source, "registry")

    def test_missing_optional_fields_become_empty_strings(self):
        record = record_from_entry({"DisplayName": "Foo"})
        self.assertEqual(record.version, "")
        self.assertEqual(record.publisher, "")
        self.assertEqual(record.install_location, "")


class NormalizeNameTest(unittest.TestCase):
    def test_collapses_whitespace_and_case(self):
        self.assertEqual(normalize_name("  Google  Chrome "), normalize_name("google chrome"))


class MergeRecordsTest(unittest.TestCase):
    def test_identical_name_and_version_collapse_into_one(self):
        records = [
            SoftwareRecord(name="Foo", version="1.0", publisher="Bar"),
            SoftwareRecord(name="foo ", version="1.0", install_location="C:\\Foo"),
        ]
        merged = merge_records(records)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].publisher, "Bar")
        self.assertEqual(merged[0].install_location, "C:\\Foo")

    def test_different_versions_are_kept_apart(self):
        records = [
            SoftwareRecord(name="Foo", version="1.0"),
            SoftwareRecord(name="Foo", version="2.0"),
        ]
        self.assertEqual(len(merge_records(records)), 2)

    def test_record_with_package_id_wins_over_plain_one(self):
        records = [
            SoftwareRecord(name="Foo", version="1.0", source="registry"),
            SoftwareRecord(name="Foo", version="1.0", source="winget", package_id="Foo.Bar"),
        ]
        merged = merge_records(records)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].package_id, "Foo.Bar")
        self.assertEqual(merged[0].source, "winget")


class CollectTest(unittest.TestCase):
    def test_collect_filters_blank_name_out_of_reader_output(self):
        entries = [
            {"DisplayName": "Foo", "DisplayVersion": "1.0"},
            {"DisplayName": ""},
            {"DisplayVersion": "9.9"},
        ]
        records = collect(entry_reader=lambda: entries)
        self.assertEqual([r.name for r in records], ["Foo"])


if __name__ == "__main__":
    unittest.main()
