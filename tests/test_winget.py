"""功能 1/2 的 winget 交互层：输出解析与匹配选优。"""
import pathlib
import sys
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from software_reback.winget import (
    build_download_args,
    build_search_args,
    parse_table,
    pick_best,
    resolve_package_id,
    search_key,
)


SEARCH_OUTPUT = """Name            Id                   Version   Source
---------------------------------------------------------
7-Zip XPDM3X7FL84X2K Unknown   msstore
7-Zip 7zip.7zip      26.06     winget
"""

SEARCH_OUTPUT_WITH_MATCH_COLUMN = """Name                                                Id                                Version     Match        Source
---------------------------------------------------------------------------------------------------------------------------
Microsoft Visual Studio Installer…                  Microsoft.VisualStudio.2022.Installer 3.14.1.59822 NotInstalled winget
"""

PREAMBLE_OUTPUT = """已找到匹配的包
Name  Id  Version  Source
-------------------------
Foo   Foo.Bar  1.0  winget
"""


class ParseTableTest(unittest.TestCase):
    def test_parses_name_id_version_source(self):
        rows = parse_table(SEARCH_OUTPUT)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["name"], "7-Zip")
        self.assertEqual(rows[1]["id"], "7zip.7zip")
        self.assertEqual(rows[1]["version"], "26.06")
        self.assertEqual(rows[1]["source"], "winget")

    def test_parses_rows_with_extra_match_column(self):
        rows = parse_table(SEARCH_OUTPUT_WITH_MATCH_COLUMN)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], "Microsoft.VisualStudio.2022.Installer")
        self.assertEqual(rows[0]["source"], "winget")

    def test_ignores_preamble_lines_before_header(self):
        rows = parse_table(PREAMBLE_OUTPUT)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Foo")

    def test_returns_empty_list_without_separator(self):
        self.assertEqual(parse_table("no table here"), [])


class PickBestTest(unittest.TestCase):
    def test_prefers_winget_source_over_msstore(self):
        rows = parse_table(SEARCH_OUTPUT)
        self.assertEqual(pick_best(rows, "7-Zip"), "7zip.7zip")

    def test_matches_name_case_insensitively(self):
        rows = [{"name": "Google Chrome", "id": "Google.Chrome", "source": "winget"}]
        self.assertEqual(pick_best(rows, "google chrome"), "Google.Chrome")

    def test_matches_truncated_name_by_prefix(self):
        rows = parse_table(SEARCH_OUTPUT_WITH_MATCH_COLUMN)
        self.assertEqual(
            pick_best(rows, "Microsoft Visual Studio Installer (Preview)"),
            "Microsoft.VisualStudio.2022.Installer",
        )

    def test_returns_none_when_no_name_matches(self):
        rows = parse_table(SEARCH_OUTPUT)
        self.assertIsNone(pick_best(rows, "完全不相干的软件"))

    def test_returns_none_for_empty_rows(self):
        self.assertIsNone(pick_best([], "7-Zip"))


class SearchKeyTest(unittest.TestCase):
    def test_strips_architecture_parens(self):
        self.assertEqual(search_key("Notepad++ (64-bit x64)"), search_key("Notepad++"))

    def test_strips_trailing_version_number(self):
        self.assertEqual(search_key("OpenCode 2.0.32"), search_key("OpenCode"))

    def test_keeps_meaningful_numbers_inside_name(self):
        self.assertNotEqual(
            search_key("Microsoft Visual C++ 2013 Redistributable"),
            search_key("Microsoft Visual C++ 2015 Redistributable"),
        )


class NormalizedNameMatchTest(unittest.TestCase):
    ARCH_ROWS = [{"name": "Notepad++", "id": "Notepad++.Notepad++", "source": "winget"}]

    def test_matches_when_registry_name_has_arch_suffix(self):
        self.assertEqual(pick_best(self.ARCH_ROWS, "Notepad++ (64-bit x64)"), "Notepad++.Notepad++")

    def test_matches_when_registry_name_has_trailing_version(self):
        rows = [{"name": "OBS Studio", "id": "OBSProject.OBSStudio", "source": "winget"}]
        self.assertEqual(pick_best(rows, "OBS Studio 32.2.2"), "OBSProject.OBSStudio")

    def test_refuses_ambiguous_normalized_match(self):
        rows = [
            {"name": "Python 3.12", "id": "Python.Python.3.12", "source": "winget"},
            {"name": "Python 3.13", "id": "Python.Python.3.13", "source": "winget"},
        ]
        self.assertIsNone(pick_best(rows, "Python (64-bit)"))


class StorePackagePolicyTest(unittest.TestCase):
    """商店包默认跳过：winget download 拉商店包需要授权，重装后走 Store 库更可靠。"""

    STORE_ONLY = [{"name": "豆包", "id": "XP9B3MRZ3QB7MQ", "source": "msstore"}]

    def test_store_only_match_is_rejected_by_default(self):
        self.assertIsNone(pick_best(self.STORE_ONLY, "豆包"))

    def test_store_match_accepted_when_explicitly_allowed(self):
        self.assertEqual(pick_best(self.STORE_ONLY, "豆包", allow_store=True), "XP9B3MRZ3QB7MQ")

    def test_winget_source_still_wins_when_store_allowed(self):
        rows = [
            {"name": "7-Zip", "id": "XP00000000000", "source": "msstore"},
            {"name": "7-Zip", "id": "7zip.7zip", "source": "winget"},
        ]
        self.assertEqual(pick_best(rows, "7-Zip", allow_store=True), "7zip.7zip")


class ResolvePackageIdTest(unittest.TestCase):
    def test_queries_normalized_key_and_returns_id(self):
        queries: list[list[str]] = []

        def runner(args):
            queries.append(list(args))
            return SEARCH_OUTPUT, 0

        package_id = resolve_package_id("7-Zip 24.08 (x64)", runner)

        self.assertEqual(package_id, "7zip.7zip")
        self.assertIn("7-zip", queries[0])


class CommandArgsTest(unittest.TestCase):
    def test_search_args_use_exact_name_filter(self):
        args = build_search_args("7-Zip")
        self.assertIn("search", args)
        self.assertIn("--exact", args)
        self.assertIn("7-Zip", args)

    def test_download_args_target_specific_id_and_directory(self):
        args = build_download_args("7zip.7zip", "D:\\repo")
        self.assertIn("download", args)
        self.assertIn("7zip.7zip", args)
        self.assertIn("D:\\repo", args)
        self.assertIn("--accept-package-agreements", args)


if __name__ == "__main__":
    unittest.main()
