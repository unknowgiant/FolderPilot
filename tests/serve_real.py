# -*- coding: utf-8 -*-
"""启动真实后端 + HTTP 命令通道，供 tests/http_ui_test.mjs 做无桥环境验证。"""
import os
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
sys.path.insert(0, SRC)
from fmp.bridge import Bridge          # noqa: E402
from fmp.config import Config          # noqa: E402
from fmp.dragdrop import DragService   # noqa: E402
from fmp.model import long_path        # noqa: E402
from fmp.ops import TaskManager        # noqa: E402
from fmp.search import SearchService   # noqa: E402
from fmp.server import UIServer        # noqa: E402

cfg = Config(os.path.join(ROOT, "tests", "output", "real_cfg"))
svc = SearchService(cfg, os.path.join(SRC, "assets"), cfg.dir)
bridge = Bridge(cfg, svc, TaskManager(), DragService()).setup()
server = UIServer(os.path.join(SRC, "ui"), "real-test-token", long_path,
                  os.path.join(cfg.dir, "ui.log"), api_handler=bridge.call)
with open(os.path.join(ROOT, "tests", ".real_server_url"), "w", encoding="utf-8") as f:
    f.write(server.url)
print("REAL server:", server.url, flush=True)
while True:
    time.sleep(1)
