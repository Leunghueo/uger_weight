from __future__ import annotations

import configparser
from pathlib import Path
from _runtime import get_runtime


from PySide6.QtWidgets import QApplication


THEME_NAMES = ("light", "dark")


def apply_theme(app: QApplication, style_name: str) -> str:
    style = style_name.strip().lower()
    if style not in THEME_NAMES:
        raise f"错误的主题:{style_name}"
    theme_path = Path(get_runtime()["base_dir"] / f"runtime/theme/{style}.qss" )
    app.setStyleSheet(theme_path.read_text(encoding="utf-8"))
    return style
