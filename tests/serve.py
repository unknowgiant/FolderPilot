# -*- coding: utf-8 -*-
"""为 tests/ui_test.mjs 提供本地界面服务（仅 127.0.0.1，退出即失效）。"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
from fmp.server import UIServer          # noqa: E402
from fmp.model import long_path          # noqa: E402

server = UIServer(os.path.join(SRC, "ui"), "demo-token", long_path,
                  os.path.join(ROOT, "tests", "output", "ui.log"))
with open(os.path.join(ROOT, "tests", ".server_url"), "w", encoding="utf-8") as f:
    f.write(server.url)
print("UI server:", server.url, flush=True)
while True:
    time.sleep(1)
