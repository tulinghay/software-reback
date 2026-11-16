"""下载计划：把一条软件记录变成「怎么下」的决策。"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from software_reback.catalog import CatalogEntry
from software_reback.models import SoftwareRecord
from software_reback.resolver import plan_all, plan_for


CHROME = SoftwareRecord(name="Google Chrome", version="131.0", package_id="Google.Chrome")
NOTEPAD = SoftwareRecord(name="Notepad++", version="8.7")
VSCODE = SoftwareRecord(name="Microsoft VS Code", version="1.9")
UNKNOWN = SoftwareRecord(name="某公司内部工具", version="1.0")


class PlanForTest(unittest.TestCase):
    def test_record_with_package_id_uses_winget(self):
        plan = plan_for(CHROME)
        self.assertEqual(plan.method, "winget")
        self.assertEqual(plan.package_id, "Google.Chrome")

    def test_catalog_url_wins_over_package_id(self):
        catalog = {
            "google chrome": CatalogEntry(
                display_name="Google Chrome",
                url="https://example.com/chrome.msi",
                sha256="b" * 64,
            )
        }
        plan = plan_for(CHROME, catalog)
        self.assertEqual(plan.method, "url")
        self.assertEqual(plan.url, "https://example.com/chrome.msi")
        self.assertEqual(plan.sha256, "b" * 64)

    def test_catalog_winget_id_used_when_entry_has_no_url(self):
        catalog = {"notepad++": CatalogEntry(display_name="Notepad++", winget_id="Notepad++.Notepad++")}
        plan = plan_for(NOTEPAD, catalog)
        self.assertEqual(plan.method, "winget")
        self.assertEqual(plan.package_id, "Notepad++.Notepad++")

    def test_matcher_used_when_no_package_id_and_no_catalog(self):
        plan = plan_for(VSCODE, matcher=lambda name: "Microsoft.VisualStudioCode")
        self.assertEqual(plan.method, "winget")
        self.assertEqual(plan.package_id, "Microsoft.VisualStudioCode")

    def test_matcher_failure_falls_through_to_unresolved(self):
        plan = plan_for(UNKNOWN, matcher=lambda name: None)
        self.assertEqual(plan.method, "unresolved")
        self.assertIn("未找到", plan.reason)

    def test_unresolved_when_no_source_available(self):
        plan = plan_for(UNKNOWN)
        self.assertEqual(plan.method, "unresolved")
        self.assertEqual(plan.name, "某公司内部工具")

    def test_plan_all_returns_one_plan_per_record(self):
        plans = plan_all([CHROME, NOTEPAD, UNKNOWN], matcher=lambda name: None)
        self.assertEqual(len(plans), 3)
        self.assertEqual([plan.method for plan in plans], ["winget", "unresolved", "unresolved"])


if __name__ == "__main__":
    unittest.main()
