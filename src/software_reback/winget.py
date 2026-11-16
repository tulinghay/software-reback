"""winget 交互层：命令参数构造、表格输出解析、包 ID 匹配。

winget 不提供 JSON 输出，只能解析它的表格。表格用「2 个以上空格」分隔列，
列数会随命令变化（search 可能多一列 Match），所以解析时按表头对齐。
"""
from __future__ import annotations

import re
import subprocess
from typing import Callable, Sequence

from .inventory import normalize_name

SEPARATOR = re.compile(r"^-{3,}$")
COLUMN_SPLIT = re.compile(r"\s{2,}")
# 版本列可能出现的形态：数字开头、Unknown、Latest 等
VERSIONISH = re.compile(r"^(?:\d|unknown$|latest$|notinstalled$|n/?a$)", re.IGNORECASE)
# winget 包 ID 形态：Publisher.Product（含点）或商店包（12 位大写字母数字）
ID_CANDIDATE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]*$")
# 商店包 ID 是纯大写字母数字串，长度并不固定（实测存在 14 位的情况）
STORE_ID = re.compile(r"^[A-Z0-9]{8,24}$")


def _split_row(line: str) -> list[str]:
    """把一行表格切成 [name, id, version, ...]。

    winget 按固定列宽输出，正常情况用 2 个以上空格即可切分；
    但名称很长时列会被挤压成单空格（控制台宽度不足时更明显），
    此时改为按「包 ID 的特征」定位切分点，避免整行解析失败。
    """
    parts = COLUMN_SPLIT.split(line.strip())
    if len(parts) >= 4:
        return parts

    tokens = line.split()
    for index, token in enumerate(tokens[:-1]):
        if not ID_CANDIDATE.match(token) or len(token) < 6:
            continue
        if "." not in token and not STORE_ID.match(token):
            continue
        # 包 ID 之后必须紧跟版本信息，否则这个 token 只是软件名的一部分（如 Node.js）
        if not VERSIONISH.match(tokens[index + 1]):
            continue
        return [" ".join(tokens[:index]), token, *tokens[index + 1 :]]
    return parts

WingetRunner = Callable[[Sequence[str]], tuple[str, int]]


# 注册表里的软件名常带架构/语言括号与尾部版本号，需要剥掉才能与 winget 名称对齐
PAREN_NOISE = re.compile(r"[（(][^()（）]*[)）]")
TRAILING_VERSION = re.compile(r"\s*(?:版本|ver(?:sion)?|v)?\s*\d+(?:[.\-]\d+)*\s*$", re.IGNORECASE)


def search_key(name: object) -> str:
    """把软件名归一化成可比较的检索键：去括号说明、去尾部版本号、统一空白与大小写。

    只剥「尾部」和「括号」，名称中间的版本语义（如 C++ 2013）会保留，避免误匹配。
    """
    text = PAREN_NOISE.sub(" ", str(name or ""))
    previous = None
    while previous != text:
        previous = text
        text = TRAILING_VERSION.sub("", text)
    return normalize_name(text)


def parse_table(output: str) -> list[dict[str, str]]:
    """把 winget 的表格输出解析成行字典；没有表格时返回空列表。"""
    lines = output.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    separator_index = None
    for index, line in enumerate(lines):
        if SEPARATOR.match(line.strip()):
            separator_index = index
            break
    if separator_index is None or separator_index == 0:
        return []

    columns = [column.strip().lower() for column in COLUMN_SPLIT.split(lines[separator_index - 1].strip())]
    rows: list[dict[str, str]] = []
    for line in lines[separator_index + 1 :]:
        if not line.strip():
            continue
        parts = _split_row(line)
        if len(parts) < 3:
            continue
        if len(parts) == len(columns):
            rows.append(dict(zip(columns, parts)))
        else:
            rows.append({"name": parts[0], "id": parts[1], "version": parts[2], "source": parts[-1]})
    return rows


def _name_matches(candidate: str, target: str) -> bool:
    if not candidate:
        return False
    truncated = candidate.endswith("…") or candidate.endswith("...")
    if truncated:
        core = candidate.rstrip("…").rstrip(".").strip()
        return bool(core) and target.startswith(core)
    return candidate == target


def _best_id(rows: Sequence[dict[str, str]]) -> str | None:
    ordered = sorted(rows, key=lambda row: 0 if str(row.get("source") or "").lower() == "winget" else 1)
    package_id = (ordered[0].get("id") or "").strip()
    return package_id or None


def pick_best(
    rows: Sequence[dict[str, str]], name: str, allow_store: bool = False
) -> str | None:
    """在搜索结果里挑出与软件名最匹配的包 ID。

    两轮匹配：先要求名字精确相同（含表头截断的前缀匹配）；
    不中时按归一化检索键对齐（去掉「(64-bit x64)」「8.9.8.1」这类噪声）。
    第二轮只有在候选 ID 唯一时才采用——宁可漏装，也不装错。

    allow_store=False 时忽略 msstore 结果：`winget download` 拉商店包需要额外授权，
    这类应用重装后从 Microsoft Store「我的库」还原更可靠。
    """
    if not allow_store:
        rows = [row for row in rows if str(row.get("source") or "").lower() == "winget"]
    if not rows:
        return None

    target = normalize_name(name)
    exact = [row for row in rows if _name_matches(normalize_name(row.get("name")), target)]
    if exact:
        return _best_id(exact)

    key = search_key(name)
    if not key:
        return None
    loose = [
        row
        for row in rows
        if (row.get("id") or "").strip() and search_key(row.get("name")) == key
    ]
    winget_only = [row for row in loose if str(row.get("source") or "").lower() == "winget"]
    for candidates in (winget_only, loose):
        ids = {(row.get("id") or "").strip() for row in candidates}
        if len(ids) == 1:
            return ids.pop()
    return None


def build_search_args(name: str) -> list[str]:
    return [
        "search",
        "--name",
        name,
        "--exact",
        "--accept-source-agreements",
        "--disable-interactivity",
    ]


def build_download_args(package_id: str, destination: str) -> list[str]:
    return [
        "download",
        "--id",
        package_id,
        "--exact",
        "--download-directory",
        destination,
        "--accept-package-agreements",
        "--accept-source-agreements",
        "--disable-interactivity",
    ]


def run_winget(args: Sequence[str], timeout: int = 900) -> tuple[str, int]:
    """真实执行 winget，标准输出与错误合并返回，方便统一解析。"""
    completed = subprocess.run(
        ["winget", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return (completed.stdout or "") + (completed.stderr or ""), completed.returncode


def search_by_name(name: str, runner: WingetRunner = run_winget) -> list[dict[str, str]]:
    output, _ = runner(build_search_args(name))
    return parse_table(output)


def resolve_package_id(name: str, runner: WingetRunner = run_winget) -> str | None:
    """用归一化后的名字去搜 winget，再按原名判定匹配，避免直接拿带噪声的名字搜索。"""
    query = search_key(name) or name
    rows = search_by_name(query, runner)
    if not rows and query != name:
        rows = search_by_name(name, runner)
    return pick_best(rows, name)


def download_with_winget(
    package_id: str, destination: str, runner: WingetRunner = run_winget
) -> tuple[bool, str]:
    output, code = runner(build_download_args(package_id, destination))
    return code == 0, output
