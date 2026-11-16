"""下载器：走真实 HTTP（本地起一个静态服务器），验证落盘与哈希校验。"""
import hashlib
import http.server
import pathlib
import socketserver
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

from software_reback.downloader import HashMismatch, download_url, sha256_of_file


PAYLOAD = (b"fake-installer-payload\n" * 200)


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        """静默访问日志，保持测试输出干净。"""


class _Server:
    """临时静态文件服务器，避免用 mock 假装网络。"""

    def __init__(self, directory: pathlib.Path):
        self.directory = str(directory)
        handler = lambda *args, **kwargs: _QuietHandler(
            *args, directory=self.directory, **kwargs
        )
        self.httpd = socketserver.TCPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        return f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def __exit__(self, *exc_info):
        self.httpd.shutdown()
        self.httpd.server_close()


class DownloadUrlTest(unittest.TestCase):
    def _serve(self, tmp: str) -> tuple[pathlib.Path, str]:
        source_dir = pathlib.Path(tmp) / "remote"
        source_dir.mkdir()
        (source_dir / "app-setup.msi").write_bytes(PAYLOAD)
        digest = hashlib.sha256(PAYLOAD).hexdigest()
        return source_dir, digest

    def test_downloads_file_and_verifies_sha256(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, digest = self._serve(tmp)
            dest = pathlib.Path(tmp) / "down"
            with _Server(pathlib.Path(tmp) / "remote") as base:
                path = download_url(f"{base}/app-setup.msi", dest, sha256=digest)

            self.assertEqual(path.name, "app-setup.msi")
            self.assertEqual(path.read_bytes(), PAYLOAD)

    def test_hash_mismatch_raises_and_leaves_no_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._serve(tmp)
            dest = pathlib.Path(tmp) / "down"
            with _Server(pathlib.Path(tmp) / "remote") as base:
                with self.assertRaises(HashMismatch):
                    download_url(f"{base}/app-setup.msi", dest, sha256="0" * 64)

            leftovers = list(dest.glob("*")) if dest.exists() else []

        self.assertEqual(leftovers, [])

    def test_file_name_override_is_used(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, digest = self._serve(tmp)
            dest = pathlib.Path(tmp) / "down"
            with _Server(pathlib.Path(tmp) / "remote") as base:
                path = download_url(
                    f"{base}/app-setup.msi", dest, file_name="7zip.msi", sha256=digest
                )

        self.assertEqual(path.name, "7zip.msi")

    def test_creates_destination_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, digest = self._serve(tmp)
            dest = pathlib.Path(tmp) / "a" / "b" / "c"
            with _Server(pathlib.Path(tmp) / "remote") as base:
                path = download_url(f"{base}/app-setup.msi", dest, sha256=digest)

            self.assertTrue(path.parent.is_dir())

    def test_reports_progress_bytes(self):
        seen = []
        with tempfile.TemporaryDirectory() as tmp:
            _, digest = self._serve(tmp)
            with _Server(pathlib.Path(tmp) / "remote") as base:
                download_url(
                    f"{base}/app-setup.msi",
                    pathlib.Path(tmp) / "down",
                    sha256=digest,
                    progress=lambda done, total: seen.append(done),
                )

        self.assertTrue(seen)
        self.assertEqual(seen[-1], len(PAYLOAD))


class CaBundleTest(unittest.TestCase):
    """证书包缺失要在发起网络请求前就报错，而不是静默降级为不校验。"""

    def test_missing_ca_bundle_fails_before_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                download_url(
                    "https://127.0.0.1:1/none",
                    pathlib.Path(tmp) / "down",
                    ca_bundle=pathlib.Path(tmp) / "absent.pem",
                )


class Sha256Test(unittest.TestCase):
    def test_matches_hashlib(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "f.bin"
            path.write_bytes(PAYLOAD)
            digest = sha256_of_file(path)
        self.assertEqual(digest, hashlib.sha256(PAYLOAD).hexdigest())


if __name__ == "__main__":
    unittest.main()
