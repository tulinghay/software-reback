"""软件目录（catalog）：为 winget 覆盖不到的软件维护「去哪下、怎么校验」。

目录只存元数据，不存安装包本体——这是本工具不需要额外存储介质的前提。
"""
from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass

from .inventory import normalize_name


@dataclass(slots=True)
class CatalogEntry:
    display_name: str
    url: str = ""
    file_name: str = ""
    sha256: str = ""
    winget_id: str = ""
    silent_args: str = ""


def load_catalog(path: str | pathlib.Path) -> dict[str, CatalogEntry]:
    """读取目录文件，返回 {归一化显示名: 条目}。文件不存在会抛 FileNotFoundError。"""
    path = pathlib.Path(path)
    if not path.exists():
        raise FileNotFoundError(f"软件目录文件不存在：{path}")
    data = json.loads(path.read_text(encoding="utf-8"))

    catalog: dict[str, CatalogEntry] = {}
    for item in data.get("entries", []):
        display_name = str(item.get("display_name") or "").strip()
        if not display_name:
            continue
        catalog[normalize_name(display_name)] = CatalogEntry(
            display_name=display_name,
            url=str(item.get("url") or "").strip(),
            file_name=str(item.get("file_name") or "").strip(),
            sha256=str(item.get("sha256") or "").strip(),
            winget_id=str(item.get("winget_id") or "").strip(),
            silent_args=str(item.get("silent_args") or "").strip(),
        )
    return catalog


def find_entry(catalog: dict[str, CatalogEntry] | None, name: str) -> CatalogEntry | None:
    if not catalog:
        return None
    return catalog.get(normalize_name(name))
