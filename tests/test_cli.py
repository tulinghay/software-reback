"""CLI 编排：扫描与下载两条命令，依赖可注入以便离线测试。"""
import csv
import json
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from software_reback import cli
from software_reback.models import SoftwareRecord
from software_reback.store import save_inventory


class RunScanTest(unittest.TestCase):
    def test_writes_json_from_injected_collector(self):
        records = [SoftwareRecord(name="Foo", version="1.0"), SoftwareRecord(name="Bar")]
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "software.json"
            returned = cli.run_scan(output, collect_fn=lambda: records, log=lambda *a: None)
            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(returned, records)
        self.assertEqual([item["name"] for item in data["software"]], ["Foo", "Bar"])

    def test_enrich_fills_package_id_from_resolver(self):
        records = [SoftwareRecord(name="Foo")]
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "software.json"
            cli.run_scan(
                output,
                collect_fn=lambda: records,
                enrich=True,
                resolve_id=lambda name: "Foo.Bar",
                log=lambda *a: None,
            )
            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(data["software"][0]["package_id"], "Foo.Bar")
        self.assertEqual(data["software"][0]["source"], "winget")

    def test_enrich_keeps_record_when_no_match(self):
        records = [SoftwareRecord(name="Foo")]
        with tempfile.TemporaryDirectory() as tmp:
            output = pathlib.Path(tmp) / "software.json"
            cli.run_scan(
                output,
                collect_fn=lambda: records,
                enrich=True,
                resolve_id=lambda name: None,
                log=lambda *a: None,
            )
            data = json.loads(output.read_text(encoding="utf-8"))

        self.assertEqual(data["software"][0]["package_id"], "")
        self.assertEqual(data["software"][0]["source"], "registry")


class RunDownloadTest(unittest.TestCase):
    def _records_file(self, tmp: str) -> pathlib.Path:
        path = pathlib.Path(tmp) / "software.json"
        save_inventory(
            [
                SoftwareRecord(name="有包ID", package_id="Foo.Bar", source="winget"),
                SoftwareRecord(name="没来源"),
            ],
            path,
        )
        return path

    def test_dry_run_plans_without_downloading(self):
        calls = []
        with tempfile.TemporaryDirectory() as tmp:
            source = self._records_file(tmp)
            report = pathlib.Path(tmp) / "report.csv"
            outcomes = cli.run_download(
                source,
                dest=pathlib.Path(tmp) / "downloads",
                matcher=lambda name: None,
                dry_run=True,
                report_path=report,
                url_downloader=lambda *a, **k: calls.append("url"),
                winget_downloader=lambda *a, **k: calls.append("winget"),
                log=lambda *a: None,
            )
            with report.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.DictReader(handle))

        self.assertEqual(calls, [])
        self.assertEqual([row["status"] for row in rows], ["planned", "skipped"])

    def test_winget_failure_is_recorded_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._records_file(tmp)
            report = pathlib.Path(tmp) / "report.csv"
            outcomes = cli.run_download(
                source,
                dest=pathlib.Path(tmp) / "downloads",
                matcher=lambda name: None,
                report_path=report,
                winget_downloader=lambda package_id, dest: (False, "hash mismatch"),
                log=lambda *a: None,
            )

        self.assertEqual(outcomes[0].status, "failed")
        self.assertIn("hash mismatch", outcomes[0].detail)

    def test_winget_success_records_actual_artifact_path(self):
        def fake_winget(package_id, dest):
            target = pathlib.Path(dest)
            target.mkdir(parents=True, exist_ok=True)
            (target / "7z.msi").write_bytes(b"x")
            return True, "done"

        with tempfile.TemporaryDirectory() as tmp:
            source = self._records_file(tmp)
            outcomes = cli.run_download(
                source,
                dest=pathlib.Path(tmp) / "downloads",
                matcher=lambda name: None,
                report_path=pathlib.Path(tmp) / "report.csv",
                winget_downloader=fake_winget,
                log=lambda *a: None,
            )

        self.assertEqual(outcomes[0].status, "ok")
        self.assertIn("7z.msi", outcomes[0].target)

    def test_url_download_records_artifact_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "software.json"
            save_inventory([SoftwareRecord(name="直链软件")], path)
            catalog = pathlib.Path(tmp) / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {"entries": [{"display_name": "直链软件", "url": "https://example.com/a.msi"}]}
                ),
                encoding="utf-8",
            )
            report = pathlib.Path(tmp) / "report.csv"
            outcomes = cli.run_download(
                path,
                dest=pathlib.Path(tmp) / "downloads",
                catalog_path=catalog,
                use_name_match=False,
                report_path=report,
                url_downloader=lambda url, dest, **kwargs: pathlib.Path(dest) / "a.msi",
                log=lambda *a: None,
            )

        self.assertEqual(outcomes[0].status, "ok")
        self.assertEqual(pathlib.Path(outcomes[0].target).name, "a.msi")

    def test_ca_bundle_is_forwarded_to_url_downloader(self):
        captured = {}

        def fake_download(url, dest, **kwargs):
            captured.update(kwargs)
            return pathlib.Path(dest) / "a.msi"

        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "software.json"
            save_inventory([SoftwareRecord(name="直链软件")], path)
            catalog = pathlib.Path(tmp) / "catalog.json"
            catalog.write_text(
                json.dumps(
                    {"entries": [{"display_name": "直链软件", "url": "https://example.com/a.msi"}]}
                ),
                encoding="utf-8",
            )
            cli.run_download(
                path,
                dest=pathlib.Path(tmp) / "downloads",
                catalog_path=catalog,
                use_name_match=False,
                ca_bundle="C:\\certs\\ca.pem",
                report_path=pathlib.Path(tmp) / "report.csv",
                url_downloader=fake_download,
                log=lambda *a: None,
            )

        self.assertEqual(captured.get("ca_bundle"), "C:\\certs\\ca.pem")


if __name__ == "__main__":
    unittest.main()
