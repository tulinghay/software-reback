"""命令行入口：scan 读取软件信息，download 按清单下载软件包。"""
from __future__ import annotations

import argparse
import pathlib
from typing import Callable, Iterable, Sequence

from . import winget
from .catalog import load_catalog
from .downloader import download_url
from .inventory import collect
from .models import SoftwareRecord
from .resolver import plan_all
from .store import DownloadOutcome, load_inventory, save_inventory, write_report


def run_scan(
    output: str | pathlib.Path,
    collect_fn: Callable[[], list[SoftwareRecord]] = collect,
    enrich: bool = False,
    resolve_id: Callable[[str], str | None] | None = None,
    log: Callable[[str], None] = print,
) -> list[SoftwareRecord]:
    """功能 1：读取本机软件信息并落盘为 JSON 清单。"""
    records = collect_fn()
    if enrich:
        resolver = resolve_id or winget.resolve_package_id
        for index, record in enumerate(records, start=1):
            if record.package_id:
                continue
            log(f"[{index}/{len(records)}] 匹配 winget 包 ID：{record.name}")
            package_id = resolver(record.name)
            if package_id:
                record.package_id = package_id
                record.source = "winget"

    path = save_inventory(records, output)
    log(f"已读取 {len(records)} 个软件，清单写入：{path}")
    return records


def _default_matcher() -> Callable[[str], str | None]:
    return winget.resolve_package_id


def run_download(
    input_path: str | pathlib.Path,
    dest: str | pathlib.Path,
    catalog_path: str | pathlib.Path | None = None,
    use_name_match: bool = True,
    matcher: Callable[[str], str | None] | None = None,
    dry_run: bool = False,
    report_path: str | pathlib.Path | None = None,
    ca_bundle: str | pathlib.Path | None = None,
    url_downloader: Callable[..., pathlib.Path] = download_url,
    winget_downloader: Callable[[str, str], tuple[bool, str]] = winget.download_with_winget,
    log: Callable[[str], None] = print,
) -> list[DownloadOutcome]:
    """功能 2：按清单解析下载来源并逐个下载。"""
    records = load_inventory(input_path)
    catalog = load_catalog(catalog_path) if catalog_path else None
    effective_matcher = matcher
    if effective_matcher is None and use_name_match:
        effective_matcher = _default_matcher()

    plans = plan_all(records, catalog, effective_matcher)
    destination = pathlib.Path(dest)
    outcomes: list[DownloadOutcome] = []

    for index, plan in enumerate(plans, start=1):
        version = plan.record.version if plan.record else ""
        if plan.method == "unresolved":
            outcomes.append(
                DownloadOutcome(name=plan.name, method=plan.method, status="skipped", version=version, detail=plan.reason)
            )
            continue

        if dry_run:
            outcomes.append(
                DownloadOutcome(
                    name=plan.name,
                    method=plan.method,
                    status="planned",
                    version=version,
                    target=plan.url or plan.package_id,
                )
            )
            continue

        log(f"[{index}/{len(plans)}] {plan.method} 下载：{plan.name}")
        try:
            if plan.method == "url":
                kwargs = {"file_name": plan.file_name, "sha256": plan.sha256}
                if ca_bundle:
                    kwargs["ca_bundle"] = ca_bundle
                artifact = url_downloader(plan.url, destination, **kwargs)
                outcomes.append(
                    DownloadOutcome(name=plan.name, method=plan.method, status="ok", version=version, target=str(artifact))
                )
            else:
                before = _snapshot(destination)
                ok, output = winget_downloader(plan.package_id, str(destination))
                if ok:
                    added = sorted(_snapshot(destination) - before)
                    target = "; ".join(str(path) for path in added) if added else plan.package_id
                    outcomes.append(
                        DownloadOutcome(
                            name=plan.name, method=plan.method, status="ok", version=version, target=target
                        )
                    )
                else:
                    outcomes.append(
                        DownloadOutcome(
                            name=plan.name,
                            method=plan.method,
                            status="failed",
                            version=version,
                            target=plan.package_id,
                            detail=_tail(output),
                        )
                    )
        except Exception as exc:  # 单个软件失败不应中断整批
            outcomes.append(
                DownloadOutcome(
                    name=plan.name, method=plan.method, status="failed", version=version, target=plan.url, detail=str(exc)
                )
            )

    report = pathlib.Path(report_path) if report_path else pathlib.Path(input_path).with_name("download-report.csv")
    write_report(outcomes, report)

    counts: dict[str, int] = {}
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
    log("下载完成：" + "，".join(f"{status} {count}" for status, count in counts.items()))
    log(f"详细报告：{report}")
    return outcomes


def _snapshot(directory: pathlib.Path) -> set[pathlib.Path]:
    """目录下已有文件集合，用来算出 winget 这次新落了哪些包。"""
    if not directory.exists():
        return set()
    return {path for path in directory.rglob("*") if path.is_file()}


def _tail(text: str, limit: int = 300) -> str:
    collapsed = " ".join(str(text or "").split())
    return collapsed[-limit:]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="software-reback",
        description="读取 Windows 已安装软件清单，并按清单下载安装包。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan", help="读取本机软件信息（功能 1）")
    scan.add_argument("-o", "--output", default="software.json", help="清单输出路径")
    scan.add_argument("--enrich", action="store_true", help="用 winget 搜索补齐包 ID（较慢，需联网）")

    download = subparsers.add_parser("download", help="按清单下载软件包（功能 2）")
    download.add_argument("-i", "--input", default="software.json", help="清单文件路径")
    download.add_argument("-d", "--dest", default="downloads", help="安装包存放目录")
    download.add_argument("--catalog", default=None, help="软件目录 JSON（直链与哈希）")
    download.add_argument("--no-name-match", action="store_true", help="关闭按名称自动匹配 winget")
    download.add_argument("--dry-run", action="store_true", help="只生成下载计划，不实际下载")
    download.add_argument("--report", default=None, help="报告 CSV 输出路径")
    download.add_argument("--ca-bundle", default=None, help="自定义 CA 证书包（HTTPS 校验失败时使用）")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "scan":
        run_scan(args.output, enrich=args.enrich)
        return 0

    outcomes = run_download(
        args.input,
        args.dest,
        catalog_path=args.catalog,
        use_name_match=not args.no_name_match,
        dry_run=args.dry_run,
        report_path=args.report,
        ca_bundle=args.ca_bundle,
    )
    failed = [outcome for outcome in outcomes if outcome.status == "failed"]
    if failed:
        print(f"有 {len(failed)} 个软件下载失败，详见报告。")
        return 2
    return 0
