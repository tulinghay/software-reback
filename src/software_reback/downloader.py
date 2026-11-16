"""下载器：HTTP 流式下载 + SHA256 校验，先写 .part 再原子改名。

只用标准库，不引入第三方依赖；下载过程中的半成品文件不会留下。
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import re
import ssl
import urllib.parse
import urllib.request
from typing import Callable

CHUNK_SIZE = 1024 * 1024
_UNSAFE = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_STOP_WORDS = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}


class DownloadError(Exception):
    """下载失败的基类。"""


class HashMismatch(DownloadError):
    """实际下载内容的 SHA256 与期望值不一致。"""


def sha256_of_file(path: str | pathlib.Path, chunk_size: int = CHUNK_SIZE) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_file_name(name: str) -> str:
    """把任意名字压成 Windows 可用文件名，并挡住保留设备名。"""
    cleaned = _UNSAFE.sub("_", name).strip(" .")
    if not cleaned:
        cleaned = "download.bin"
    stem = cleaned.split(".")[0].lower()
    if stem in _STOP_WORDS:
        cleaned = f"_{cleaned}"
    return cleaned


def _file_name_from_url(url: str) -> str:
    path = urllib.parse.urlparse(url).path
    name = pathlib.PurePosixPath(path).name
    return safe_file_name(urllib.parse.unquote(name)) if name else "download.bin"


def build_ssl_context(ca_bundle: str | pathlib.Path | None) -> ssl.SSLContext | None:
    """指定 CA 证书包时用它建上下文；始终开启证书校验，不做「不校验」的降级。"""
    if not ca_bundle:
        return None
    path = pathlib.Path(ca_bundle)
    if not path.exists():
        raise FileNotFoundError(f"CA 证书包不存在：{path}")
    return ssl.create_default_context(cafile=str(path))


def download_url(
    url: str,
    dest_dir: str | pathlib.Path,
    file_name: str = "",
    sha256: str = "",
    timeout: int = 60,
    progress: Callable[[int, int], None] | None = None,
    ca_bundle: str | pathlib.Path | None = None,
) -> pathlib.Path:
    """下载到 dest_dir，返回落盘路径；校验不通过会抛 HashMismatch。"""
    context = build_ssl_context(ca_bundle)

    destination_dir = pathlib.Path(dest_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)
    target = destination_dir / (safe_file_name(file_name) if file_name else _file_name_from_url(url))
    temp = target.with_name(target.name + ".part")

    digest = hashlib.sha256()
    received = 0
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "software-reback/0.1"})
        with urllib.request.urlopen(request, timeout=timeout, context=context) as response, open(temp, "wb") as handle:
            total = int(response.headers.get("Content-Length") or 0)
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                handle.write(chunk)
                digest.update(chunk)
                received += len(chunk)
                if progress:
                    progress(received, total)

        actual = digest.hexdigest()
        if sha256 and actual.lower() != sha256.strip().lower():
            raise HashMismatch(f"SHA256 校验失败：期望 {sha256}，实际 {actual}")
        os.replace(temp, target)
    except BaseException:
        temp.unlink(missing_ok=True)
        raise

    return target
