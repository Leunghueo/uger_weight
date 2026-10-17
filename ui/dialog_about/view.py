from __future__ import annotations

import hashlib
import uuid

import psutil
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "XLT静载实验台上位机程序"
APP_VERSION = "1.0.0"


class Window(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"关于 {APP_NAME}")
        self.setMinimumWidth(480)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 24, 24, 18)
        root.setSpacing(18)

        header = QWidget(self)
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.setSpacing(16)

        logo = QLabel("XLT", header)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFixedSize(72, 72)
        logo.setStyleSheet(
            """
            QLabel {
                background: #1f6feb;
                color: white;
                border-radius: 8px;
                font-size: 24px;
                font-weight: 700;
            }
            """
        )
        header_layout.addWidget(logo)

        title_box = QVBoxLayout()
        title_box.setContentsMargins(0, 0, 0, 0)
        title_box.setSpacing(6)

        title = QLabel(APP_NAME, header)
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        title.setWordWrap(True)
        title_box.addWidget(title)

        version = QLabel(f"版本 {APP_VERSION}", header)
        version.setStyleSheet("color: #5f6b7a; font-size: 13px;")
        title_box.addWidget(version)
        title_box.addStretch(1)

        header_layout.addLayout(title_box, 1)
        root.addWidget(header)

        separator = QFrame(self)
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        root.addWidget(separator)

        description = QLabel(
            "用于 XLT 静载实验台的数据采集、试验流程控制、设备状态监控与参数配置。",
            self,
        )
        description.setWordWrap(True)
        description.setStyleSheet("line-height: 1.4;")
        root.addWidget(description)

        info = QLabel(
            "Copyright (C) 2026\n"
            "保留所有权利。",
            self,
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #5f6b7a;")
        root.addWidget(info)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)

        export_btn = QPushButton("导出请求码", self)
        export_btn.clicked.connect(self.export_request_code)
        button_row.addWidget(export_btn)

        button_row.addStretch(1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, parent=self)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText("关闭")
        buttons.rejected.connect(self.reject)
        button_row.addWidget(buttons)

        root.addLayout(button_row)

    def generate_request_code(self):
        # Simulate request code generation
        cpu_info = str(psutil.cpu_count())
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> i) & 0xff) for i in range(0, 48, 8)])
        mem = str(psutil.virtual_memory().total)
        combined = (cpu_info + mac + mem).encode()
        hash = hashlib.sha256(combined).hexdigest()
        return f"xlt::bogie::v1.0::{hash}"

    def export_request_code(self):
        file_path, _ = QFileDialog.getSaveFileName(
            self, "保存请求码", "", "XLT Files (*.xlt);;All Files (*)"
        )
        if file_path:
            with open(file_path, 'w') as file:
                file.write(self.generate_request_code())