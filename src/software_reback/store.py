"""清单与报告的读写。"""
from __future__ import annotations

import csv
import json
import pathlib
from dataclasses import dataclass
from datetime import datetime
from typing import Iterable, Sequence

from .models import SoftwareRecord

SCHEMA_VERSION = 1
REPORT_FIELDS = ("name", "version", "method", "status", "target", "detail")


@dataclass(slots=True)
class DownloadOutcome:
    """一次下载动作的结果，最终落成 CSV 里的一行。"""

    name: str
    method: str
    status: str  # ok | failed | skipped | planned
    version: str = ""
    target: str = ""
    detail: str = ""


def save_inventory(records: Iterable[SoftwareRecord], path: str | pathlib.Path) -> pathlib.Path:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "software": [record.to_dict() for record in records],
    }
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def load_inventory(path: str | pathlib.Path) -> list[SoftwareRecord]:
    source = pathlib.Path(path)
    data = json.loads(source.read_text(encoding="utf-8"))
    items = data.get("software") if isinstance(data, dict) else data
    return [SoftwareRecord.from_dict(item) for item in (items or [])]


def write_report(outcomes: Sequence[DownloadOutcome], path: str | pathlib.Path) -> pathlib.Path:
    target = pathlib.Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REPORT_FIELDS)
        writer.writeheader()
        for outcome in outcomes:
            writer.writerow(
                {
                    "name": outcome.name,
                    "version": outcome.version,
                    "method": outcome.method,
                    "status": outcome.status,
                    "target": outcome.target,
                    "detail": outcome.detail,
                }
            )
    return target
