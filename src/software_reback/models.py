"""数据模型：一条软件记录就是清单里的一行。"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass


@dataclass(slots=True)
class SoftwareRecord:
    """一台机器上已安装的一个软件。

    source 表示记录来源：registry（注册表）、winget（winget 识别到包 ID）、store。
    package_id 为 winget 包标识符，有它就代表可以走 winget 通道下载。
    """

    name: str
    version: str = ""
    publisher: str = ""
    install_location: str = ""
    source: str = "registry"
    package_id: str = ""

    def to_dict(self) -> dict:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "SoftwareRecord":
        allowed = {field.name for field in dataclasses.fields(cls)}
        return cls(**{key: value for key, value in data.items() if key in allowed})
