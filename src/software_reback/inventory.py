"""功能 1：读取本机已安装软件信息。

数据来源是 Windows 卸载项注册表的三个位置（HKLM 64 位、HKLM 32 位、HKCU），
思路与「设置 → 应用 → 已安装的应用」一致：只保留有显示名、且不是系统组件/补丁的记录。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Callable, Iterable, Mapping

from .models import SoftwareRecord

# (注册表根, 卸载项路径)
REGISTRY_ROOTS = (
    ("HKLM", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKLM", r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"),
    ("HKCU", r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"),
)


def normalize_name(name: object) -> str:
    """比较/去重用的软件名：压缩空白并忽略大小写。"""
    return " ".join(str(name or "").split()).casefold()


def _is_truthy(value: object) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    return bool(value) and not isinstance(value, (list, dict))


def record_from_entry(entry: Mapping[str, object]) -> SoftwareRecord | None:
    """把一条注册表卸载项转成 SoftwareRecord；无意义的条目返回 None。"""
    name = str(entry.get("DisplayName") or "").strip()
    if not name:
        return None
    if _is_truthy(entry.get("SystemComponent")):
        return None
    if str(entry.get("ParentKeyName") or "").strip():
        return None
    return SoftwareRecord(
        name=name,
        version=str(entry.get("DisplayVersion") or "").strip(),
        publisher=str(entry.get("Publisher") or "").strip(),
        install_location=str(entry.get("InstallLocation") or "").strip(),
        source="registry",
    )


def _completeness(record: SoftwareRecord) -> tuple:
    """信息越全的条目越可信，去重时优先保留它。"""
    return (
        1 if record.package_id else 0,
        1 if record.publisher else 0,
        1 if record.install_location else 0,
        1 if record.source != "registry" else 0,
    )


def merge_records(records: Iterable[SoftwareRecord]) -> list[SoftwareRecord]:
    """同名同版本的多条记录合并成一条，缺失字段用其余记录补齐。"""
    groups: dict[tuple[str, str], list[SoftwareRecord]] = {}
    for record in records:
        groups.setdefault((normalize_name(record.name), record.version), []).append(record)

    merged: list[SoftwareRecord] = []
    for items in groups.values():
        items = sorted(items, key=_completeness, reverse=True)
        best = items[0]
        for other in items[1:]:
            best = replace(
                best,
                publisher=best.publisher or other.publisher,
                install_location=best.install_location or other.install_location,
            )
        merged.append(best)
    return merged


def _read_windows_registry(roots: tuple[tuple[str, str], ...] = REGISTRY_ROOTS):
    """逐个子键读取注册表卸载项，读不到的键直接跳过。"""
    import winreg

    hives = {"HKLM": winreg.HKEY_LOCAL_MACHINE, "HKCU": winreg.HKEY_CURRENT_USER}
    for hive_name, sub_path in roots:
        hive = hives[hive_name]
        try:
            root = winreg.OpenKey(hive, sub_path)
        except OSError:
            continue
        with root:
            index = 0
            while True:
                try:
                    sub_key = winreg.EnumKey(root, index)
                except OSError:
                    break
                index += 1
                try:
                    with winreg.OpenKey(hive, sub_path + "\\" + sub_key) as key:
                        entry: dict[str, object] = {}
                        value_index = 0
                        while True:
                            try:
                                value_name, value, _ = winreg.EnumValue(key, value_index)
                            except OSError:
                                break
                            value_index += 1
                            entry[value_name] = value
                        yield entry
                except OSError:
                    continue


def read_registry_entries(
    entry_reader: Callable[[], Iterable[Mapping[str, object]]] | None = None,
    roots: tuple[tuple[str, str], ...] = REGISTRY_ROOTS,
) -> list[Mapping[str, object]]:
    reader = entry_reader or (lambda: _read_windows_registry(roots))
    return list(reader())


def collect(entry_reader: Callable[[], Iterable[Mapping[str, object]]] | None = None) -> list[SoftwareRecord]:
    """功能 1 的入口：读出本机软件清单（已过滤、已去重）。"""
    records = [record for record in (record_from_entry(entry) for entry in read_registry_entries(entry_reader)) if record]
    return sorted(merge_records(records), key=lambda record: normalize_name(record.name))
