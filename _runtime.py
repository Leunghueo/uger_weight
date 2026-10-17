from __future__ import annotations

import configparser
import sys
from pathlib import Path
from typing import Any
import json

import guard

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

plc_used = config.get("plc", "used")
plc_config_path = BASE_DIR /  config.get("plc", "path")

vsp_used = BASE_DIR / config.get("vsp", "used")
vsp_config_path = BASE_DIR /  config.get("vsp", "path")

flow_template_dir = BASE_DIR /  config.get("flow", "path")
node_config_path = BASE_DIR /  config.get("node", "path")
bogie_config_path = BASE_DIR /  config.get("bogie", "path")
bed_config_path = BASE_DIR /  config.get("bed", "path")
push_config_path = BASE_DIR /  config.get("push", "path")

db_path = BASE_DIR / config.get("db", "path")
report_template = BASE_DIR / config.get("report", "template")
report_path = BASE_DIR / config.get("report", "path")
theme = config.get("theme","style")
size = (int(config.get("size","w")), int(config.get("size","h")))
# 在 _runtime.py 中添加
print(f"Runtime size: {size}")

bed_data = None
with open(bed_config_path, "r", encoding="utf-8") as f:
    bed_data = json.load(f)

init_runtime(
    base_dir=BASE_DIR,
    config=config,
    sim=sim,
    plc_used=plc_used,
    vsp_used=vsp_used,
    theme=theme,
    bed_data=bed_data,
    guard = guard,
    size = size,
    paths={
        "plc_config": plc_config_path,
        "vsp_config": vsp_config_path,
        "flow_dir": flow_template_dir,
        "node_config": node_config_path,
        "bogie_config": bogie_config_path,
        "bed_config" : bed_config_path,
        "report_template": report_template,
        "report_path": report_path,
        "push_config": push_config_path,
        "db": db_path,
    }
)
