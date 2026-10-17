from __future__ import annotations

import configparser
import sys
from pathlib import Path
from typing import Any

RUNTIME: dict[str, Any] = {}

def init_runtime(**kwargs: Any) -> dict[str, Any]:
    RUNTIME.clear()
    RUNTIME.update(kwargs)
    return RUNTIME

def update_runtime(**kwargs: Any) -> dict[str, Any]:
    RUNTIME.update(kwargs)
    return RUNTIME

def get_runtime() -> dict[str, Any]:
    if not RUNTIME:
        raise RuntimeError("程序运行时未初始化")
    return RUNTIME

BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
config = configparser.ConfigParser()
config.read(BASE_DIR / "app.ini", encoding="utf-8")

sim = config.get("sim", "enable")

vsp_config_path = BASE_DIR / config.get("vsp", "path")
maps_config_path = BASE_DIR / config.get("maps", "path")

db_path = BASE_DIR / config.get("db", "path")
report_template = BASE_DIR / config.get("report", "template")
report_path = BASE_DIR / config.get("report", "path")
theme = config.get("theme", "style")
size = (int(config.get("size", "w")), int(config.get("size", "h")))
# 在 _runtime.py 中添加
print(f"Runtime size: {size}")

init_runtime(
    base_dir=BASE_DIR,
    config=config,
    sim=sim,
    theme=theme,
    size=size,
    paths={
        "vsp_config": vsp_config_path,
        "maps_config": maps_config_path,
        "report_template": report_template,
        "report_path": report_path,
        "db": db_path,
    }
)
