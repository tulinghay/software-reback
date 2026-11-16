"""下载计划：一条软件记录 → 一个可执行的下载动作。

优先级：目录中的直链（可带 SHA256，最可控）> 记录自带的 winget 包 ID
> 名称自动匹配 winget > 无法解析（进人工清单）。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence

from .catalog import find_entry
from .models import SoftwareRecord

Matcher = Callable[[str], str | None]


@dataclass(slots=True)
class DownloadPlan:
    name: str
    method: str  # "url" | "winget" | "unresolved"
    package_id: str = ""
    url: str = ""
    file_name: str = ""
    sha256: str = ""
    reason: str = ""
    record: SoftwareRecord | None = None


def plan_for(
    record: SoftwareRecord,
    catalog: dict | None = None,
    matcher: Matcher | None = None,
) -> DownloadPlan:
    entry = find_entry(catalog, record.name)

    if entry and entry.url:
        return DownloadPlan(
            name=record.name,
            method="url",
            url=entry.url,
            file_name=entry.file_name,
            sha256=entry.sha256,
            record=record,
        )

    if entry and entry.winget_id:
        return DownloadPlan(name=record.name, method="winget", package_id=entry.winget_id, record=record)

    if record.package_id:
        return DownloadPlan(name=record.name, method="winget", package_id=record.package_id, record=record)

    if matcher:
        matched = matcher(record.name)
        if matched:
            return DownloadPlan(name=record.name, method="winget", package_id=matched, record=record)

    return DownloadPlan(
        name=record.name,
        method="unresolved",
        reason="未找到可用的下载来源（无 winget 包 ID，且不在软件目录中）",
        record=record,
    )


def plan_all(
    records: Sequence[SoftwareRecord],
    catalog: dict | None = None,
    matcher: Matcher | None = None,
) -> list[DownloadPlan]:
    return [plan_for(record, catalog, matcher) for record in records]
