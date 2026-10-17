from __future__ import annotations

import logging
import sqlite3

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from _runtime import get_runtime


logger = logging.getLogger(__name__)


class Window(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.runtime = get_runtime()
        self.username = "admin"
        self.user_class = "0"
        self._usernames = self._load_usernames()
        self.setWindowTitle("登录")
        self.setModal(True)
        self.setMinimumWidth(360)
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        card = QWidget(self)
        card.setObjectName("loginCard")
        root.addWidget(card)

        card_layout = QVBoxLayout(card)
        title = QLabel("程序登录", card)
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        card_layout.addWidget(title)

        form = QFormLayout()
        self.username_edit = QComboBox(card)
        self.username_edit.setEditable(False)
        self.username_edit.addItems(self._usernames)
        self.password_edit = QLineEdit(card)
        self.password_edit.setPlaceholderText("请输入密码")
        self.password_edit.setEchoMode(QLineEdit.Password)
        form.addRow("用户名", self.username_edit)
        form.addRow("密码", self.password_edit)
        card_layout.addLayout(form)

        actions = QHBoxLayout()
        cancel_btn = QPushButton("取消", card)
        login_btn = QPushButton("登录", card)
        cancel_btn.clicked.connect(self.reject)
        login_btn.clicked.connect(self._submit)
        actions.addWidget(cancel_btn)
        actions.addWidget(login_btn)
        card_layout.addLayout(actions)

        self.setStyleSheet(
            """
            QDialog { background: #edf2f7; }
            QWidget#loginCard {
                background: white;
                border: 1px solid #d9e2ec;
                border-radius: 12px;
                padding: 18px;
            }
            QLineEdit, QComboBox {
                padding: 8px;
                border: 1px solid #cbd5e0;
                border-radius: 6px;
                background: #f8fafc;
            }
            QPushButton {
                min-width: 100px;
                padding: 8px 12px;
            }
            """
        )

    def _load_usernames(self) -> list[str]:
        db_path = self.runtime["paths"]["db"]
        with sqlite3.connect(db_path) as conn:
            rows = conn.execute(
                """
                SELECT UserName
                FROM TblUser
                WHERE UserName IS NOT NULL AND TRIM(UserName) <> ''
                ORDER BY UserName
                """
            ).fetchall()
        return [str(row[0]).strip() for row in rows if str(row[0]).strip()]

    def _load_user(self, username: str, password: str) -> tuple[str, str] | None:
        db_path = self.runtime["paths"]["db"]
        with sqlite3.connect(db_path) as conn:
            row = conn.execute(
                """
                SELECT UserName, UserClass
                FROM TblUser
                WHERE UserName = ? AND LoginPassword = ?
                LIMIT 1
                """,
                (username, password),
            ).fetchone()
        if row is None:
            return None
        return str(row[0]), str(row[1] or "")

    def set_selected_username(self, username: str) -> None:
        index = self.username_edit.findText(username)
        if index >= 0:
            self.username_edit.setCurrentIndex(index)

    def _submit(self) -> None:
        username = self.username_edit.currentText().strip()
        password = self.password_edit.text()
        if not username:
            logger.warning(f"login failed: empty username")
            QMessageBox.warning(self, "登录失败", "用户名不能为空。")
            return

        user_row = self._load_user(username, password)
        if user_row is None:
            logger.warning(f"login failed: invalid credentials for user=%s", username)
            QMessageBox.warning(self, "登录失败", "用户名或密码错误。")
            return

        self.username, self.user_class = user_row
        self.runtime["cur_user"] = {
            "username": self.username,
            "user_class": self.user_class,
        }
        self.runtime["current_user"] = self.username
        logger.info(f"用户登录[%s]", self.username)
        self.accept()
