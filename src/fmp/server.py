# -*- coding: utf-8 -*-
"""本地传输层：静态资源、文件二进制流、业务命令（/api）。

命令通道改用带 token 的本地 HTTP，而不是 pywebview 的 js_api ——
js_api 是异步注入的，启动竞态下会出现 `api.call is not a function`。
命令与资源仍在同一服务内分层，且只绑定 127.0.0.1 + 随机 token。
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .version import APP_TITLE, APP_VERSION, DATA_DIR_DISPLAY

MIME_OVERRIDE = {"pdf": "application/pdf", "mp4": "video/mp4", "mkv": "video/x-matroska",
                 "webm": "video/webm", "mp3": "audio/mpeg", "m4a": "audio/mp4",
                 "md": "text/markdown; charset=utf-8", "js": "text/javascript; charset=utf-8",
                 "css": "text/css; charset=utf-8", "html": "text/html; charset=utf-8",
                 "json": "application/json; charset=utf-8", "svg": "image/svg+xml",
                 "webp": "image/webp", "woff2": "font/woff2"}


def make_handler(ui_dir: str, token: str, long_path, log_path: str = None, api_handler=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "FMP/" + APP_VERSION

        def log_message(self, *a):
            pass

        def _send(self, code, body=b"", ctype="application/octet-stream", extra=None):
            # 关闭窗口时浏览器会先断开连接，此处的写入必然失败且无意义，
            # 静默忽略，避免退出时刷一屏 ConnectionAbortedError 回溯。
            try:
                self.send_response(code)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                for k, v in (extra or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                if self.command != "HEAD" and body:
                    self.wfile.write(body)
            except (ConnectionError, OSError):
                self.close_connection = True

        def _static(self, rel):
            rel = rel.split("?")[0].lstrip("/") or "index.html"
            p = os.path.realpath(os.path.join(ui_dir, rel.replace("/", os.sep)))
            if not p.startswith(os.path.realpath(ui_dir) + os.sep) and p != os.path.realpath(os.path.join(ui_dir, "index.html")):
                return self._send(403, b"forbidden", "text/plain; charset=utf-8")
            if not os.path.isfile(p):
                return self._send(404, b"not found", "text/plain; charset=utf-8")
            ext = os.path.splitext(p)[1].lstrip(".").lower()
            ctype = MIME_OVERRIDE.get(ext) or mimetypes.guess_type(p)[0] or "application/octet-stream"
            with open(p, "rb") as f:
                body = f.read()
            if p.endswith("index.html"):
                body = body.replace(b"__FMP_TOKEN__", token.encode("utf-8"))
                # 版本相关文案统一由 fmp.version 注入，前端不再写死版本号
                body = body.replace(b"__FMP_TITLE__", APP_TITLE.encode("utf-8"))
                body = body.replace(b"__FMP_VERSION__", APP_VERSION.encode("utf-8"))
                body = body.replace(b"__FMP_DATA_DIR__", DATA_DIR_DISPLAY.encode("utf-8"))
            self._send(200, body, ctype)

        def _file(self, qs):
            if qs.get("t", [""])[0] != token and self.headers.get("X-FMP-Token") != token:
                return self._send(403, b"forbidden", "text/plain; charset=utf-8")
            p = qs.get("p", [""])[0]
            if not p:
                return self._send(400, b"missing p", "text/plain; charset=utf-8")
            try:
                f = open(long_path(p), "rb")
            except OSError as ex:
                return self._send(404, str(ex).encode("utf-8"), "text/plain; charset=utf-8")
            size = os.fstat(f.fileno()).st_size
            ext = os.path.splitext(p)[1].lstrip(".").lower()
            ctype = MIME_OVERRIDE.get(ext) or mimetypes.guess_type(p)[0] or "application/octet-stream"
            rng = self.headers.get("Range")
            start, end, code = 0, size - 1, 200
            if rng:
                m = re.match(r"bytes=(\d*)-(\d*)", rng)
                if m:
                    if m.group(1):
                        start = int(m.group(1))
                    if m.group(2):
                        end = min(int(m.group(2)), size - 1)
                    code = 206
            length = max(0, end - start + 1)
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(length))
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Disposition", 'inline; filename*=UTF-8\'\'' + urllib.parse.quote(os.path.basename(p)))
            if code == 206:
                self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
            self.end_headers()
            try:
                f.seek(start)
                left = length
                while left > 0:
                    chunk = f.read(min(65536, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                f.close()

        def _log(self, qs):
            """前端启动诊断日志（不依赖 js_api，桥未注入时也能记录）。"""
            if qs.get("t", [""])[0] != token:
                return self._send(403, b"forbidden", "text/plain; charset=utf-8")
            try:
                if log_path:
                    os.makedirs(os.path.dirname(log_path), exist_ok=True)
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(time.strftime("%Y-%m-%d %H:%M:%S ") +
                                qs.get("m", [""])[0][:1200] + "\n")
            except OSError:
                pass
            return self._send(200, b"ok", "text/plain; charset=utf-8")

        def _api(self, qs, raw=b""):
            """业务命令：POST JSON {method, params} 或 GET ?m=&p=。"""
            if qs.get("t", [""])[0] != token and self.headers.get("X-FMP-Token") != token:
                return self._send(403, b"forbidden", "text/plain; charset=utf-8")
            if api_handler is None:
                return self._send(503, json.dumps(
                    {"ok": False, "error": "命令服务未就绪"}, ensure_ascii=False).encode("utf-8"),
                    "application/json; charset=utf-8")
            try:
                if raw:
                    req = json.loads(raw.decode("utf-8"))
                    method, payload = req.get("method", ""), json.dumps(
                        req.get("params", {}), ensure_ascii=False)
                else:
                    method, payload = qs.get("m", [""])[0], qs.get("p", ["{}"])[0]
                result = api_handler(method, payload)
                body = result.encode("utf-8") if isinstance(result, str) else \
                    json.dumps(result, ensure_ascii=False).encode("utf-8")
                return self._send(200, body, "application/json; charset=utf-8")
            except Exception as ex:
                return self._send(200, json.dumps(
                    {"ok": False, "error": f"{type(ex).__name__}: {ex}"},
                    ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

        def do_GET(self):
            u = urllib.parse.urlparse(self.path)
            qs = urllib.parse.parse_qs(u.query)
            if u.path == "/file" or u.path == "/thumb":
                return self._file(qs)
            if u.path == "/log":
                return self._log(qs)
            if u.path == "/api":
                return self._api(qs)
            return self._static(u.path)

        def do_POST(self):
            u = urllib.parse.urlparse(self.path)
            if u.path != "/api":
                return self._send(404, b"not found", "text/plain; charset=utf-8")
            try:
                n = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                n = 0
            if n > 2 * 1024 * 1024:
                return self._send(413, b"payload too large", "text/plain; charset=utf-8")
            return self._api(urllib.parse.parse_qs(u.query), self.rfile.read(n) if n else b"")

        def do_HEAD(self):
            self.do_GET()

    return Handler


class _DaemonHTTPServer(ThreadingHTTPServer):
    # 请求线程必须是 daemon，否则退出程序时会被未完成的 HTTP 请求拖住
    daemon_threads = True
    allow_reuse_address = True


class UIServer:
    def __init__(self, ui_dir, token, long_path, log_path=None, api_handler=None):
        self.httpd = _DaemonHTTPServer(("127.0.0.1", 0),
                                       make_handler(ui_dir, token, long_path, log_path, api_handler))
        self.port = self.httpd.server_address[1]
        threading.Thread(target=lambda: self.httpd.serve_forever(poll_interval=0.1),
                         daemon=True, name="fmp-ui-server").start()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}/"

    def stop(self):
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        try:
            self.httpd.server_close()
        except Exception:
            pass
