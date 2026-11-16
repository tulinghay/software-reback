"""清单与报告的读写：JSON 清单可复用，报告用 CSV 便于人工勾选。"""
import csv
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from software_reback.models import SoftwareRecord
from software_reback.store import DownloadOutcome, load_inventory, save_inventory, write_report


def _read_rows(path: pathlib.Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


class InventoryRoundtripTest(unittest.TestCase):
    def test_save_then_load_returns_equal_records(self):
        records = [
            SoftwareRecord(name="7-Zip", version="24.08", publisher="Igor Pavlov", package_id="7zip.7zip"),
            SoftwareRecord(name="Notepad++", version="8.7"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "software.json"
            save_inventory(records, path)
            loaded = load_inventory(path)

        self.assertEqual(loaded, records)

    def test_load_ignores_unknown_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "software.json"
            path.write_text(
                '{"software": [{"name": "Foo", "unknown_field": 1}]}', encoding="utf-8"
            )
            loaded = load_inventory(path)

        self.assertEqual(loaded[0].name, "Foo")

    def test_saved_file_is_valid_json_with_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "software.json"
            save_inventory([SoftwareRecord(name="Foo")], path)
            text = path.read_text(encoding="utf-8")

        self.assertIn('"software"', text)
        self.assertIn('"schema_version"', text)


class WriteReportTest(unittest.TestCase):
    def test_writes_one_row_per_outcome(self):
        outcomes = [
            DownloadOutcome(name="Foo", method="winget", status="ok", target="Foo.Bar"),
            DownloadOutcome(name="Bar", method="unresolved", status="skipped", detail="未找到"),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "report.csv"
            write_report(outcomes, path)
            rows = _read_rows(path)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["name"], "Foo")
        self.assertEqual(rows[1]["status"], "skipped")
        self.assertEqual(set(rows[0].keys()), {"name", "version", "method", "status", "target", "detail"})

    def test_commas_in_detail_do_not_break_columns(self):
        outcomes = [DownloadOutcome(name="Foo, Inc.", method="url", status="failed", detail="超时, 重试失败")]
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "report.csv"
            write_report(outcomes, path)
            rows = _read_rows(path)

        self.assertEqual(rows[0]["name"], "Foo, Inc.")
        self.assertEqual(rows[0]["detail"], "超时, 重试失败")


if __name__ == "__main__":
    unittest.main()
