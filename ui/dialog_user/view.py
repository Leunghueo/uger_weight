from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from _runtime import get_runtime


@dataclass(frozen=True)
class UserRecord:
    row_id: int
    username: str
    user_class: str


class UserEditor(QDialog):
    def __init__(self, parent: QDialog, user: UserRecord | None = None) -> None:
        super().__init__(parent)
        self.user = user
        self.setWindowTitle("编辑用户" if user else "新增用户")
        self.setModal(True)
        self.setMinimumWidth(360)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.username_edit = QLineEdit(self)
        self.username_edit.setMaxLength(64)
        self.username_edit.setPlaceholderText("请输入用户名")
        self.password_edit = QLineEdit(self)
        self.password_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.password_edit.setPlaceholderText("留空则不修改" if self.user else "请输入密码")
        self.user_class_combo = QComboBox(self)
        self.user_class_combo.addItem("普通用户", "USER")
        self.user_class_combo.addItem("管理员", "ADMIN")

        if self.user is not None:
            self.username_edit.setText(self.user.username)
            is_admin = self.user.username.lower() == "admin" or self.user.user_class.upper() in {
                "ADMIN",
                "SUPERUSER",
            }
            self.user_class_combo.setCurrentIndex(1 if is_admin else 0)
            if self.user.username.lower() == "admin":
                self.username_edit.setReadOnly(True)
                self.user_class_combo.setEnabled(False)

        form.addRow("用户名", self.username_edit)
        form.addRow("密码", self.password_edit)
        form.addRow("用户类型", self.user_class_combo)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("保存")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self._validate)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate(self) -> None:
        if not self.username():
            QMessageBox.warning(self, "输入错误", "用户名不能为空。")
            self.username_edit.setFocus()
            return
        if self.user is None and not self.password():
            QMessageBox.warning(self, "输入错误", "新增用户时密码不能为空。")
            self.password_edit.setFocus()
            return
        self.accept()

    def username(self) -> str:
        return self.username_edit.text().strip()

    def password(self) -> str:
        return self.password_edit.text()

    def user_class(self) -> str:
        return str(self.user_class_combo.currentData())


class Window(QDialog):
    def __init__(self) -> None:
        super().__init__()
        self.runtime = get_runtime()
        self.db_path = Path(self.runtime["paths"]["db"])
        self.users: list[UserRecord] = []
        self.setWindowTitle("用户管理")
        self.setModal(True)
        self.resize(620, 420)
        self._build_ui()
        self._load_users()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("用户管理", self)
        title.setStyleSheet("font-size: 18px; font-weight: 600;")
        layout.addWidget(title)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["用户名", "用户类型", "密码"])
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.table.doubleClicked.connect(self._edit_user)
        layout.addWidget(self.table, 1)

        actions = QHBoxLayout()
        add_button = QPushButton("新增", self)
        edit_button = QPushButton("编辑", self)
        delete_button = QPushButton("删除", self)
        close_button = QPushButton("关闭", self)
        add_button.clicked.connect(self._add_user)
        edit_button.clicked.connect(self._edit_user)
        delete_button.clicked.connect(self._delete_user)
        close_button.clicked.connect(self.accept)
        actions.addWidget(add_button)
        actions.addWidget(edit_button)
        actions.addWidget(delete_button)
        actions.addStretch(1)
        actions.addWidget(close_button)
        layout.addLayout(actions)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _load_users(self) -> None:
        try:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT rowid, UserName, UserClass
                    FROM TblUser
                    WHERE UserName IS NOT NULL AND TRIM(UserName) <> ''
                    ORDER BY LOWER(UserName)
                    """
                ).fetchall()
        except sqlite3.Error as error:
            QMessageBox.critical(self, "读取失败", f"无法读取用户数据：\n{error}")
            return

        self.users = [
            UserRecord(int(row[0]), str(row[1]).strip(), str(row[2] or ""))
            for row in rows
        ]
        self.table.setRowCount(len(self.users))
        for row_index, user in enumerate(self.users):
            username_item = QTableWidgetItem(user.username)
            username_item.setData(Qt.ItemDataRole.UserRole, user.row_id)
            self.table.setItem(row_index, 0, username_item)
            self.table.setItem(row_index, 1, QTableWidgetItem(self._class_label(user)))
            password_item = QTableWidgetItem("********")
            password_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self.table.setItem(row_index, 2, password_item)

    @staticmethod
    def _class_label(user: UserRecord) -> str:
        is_admin = user.username.lower() == "admin" or user.user_class.upper() in {
            "ADMIN",
            "SUPERUSER",
        }
        if is_admin:
            return "管理员"
        return "普通用户"

    def _selected_user(self) -> UserRecord | None:
        row = self.table.currentRow()
        if row < 0:
            QMessageBox.information(self, "请选择用户", "请先在表格中选择一个用户。")
            return None
        row_id = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        return next((user for user in self.users if user.row_id == row_id), None)

    def _username_exists(self, username: str, exclude_row_id: int | None = None) -> bool:
        try:
            with self._connect() as conn:
                row = conn.execute(
                    """
                    SELECT 1 FROM TblUser
                    WHERE LOWER(UserName) = LOWER(?) AND (? IS NULL OR rowid <> ?)
                    LIMIT 1
                    """,
                    (username, exclude_row_id, exclude_row_id),
                ).fetchone()
        except sqlite3.Error as error:
            QMessageBox.critical(self, "查询失败", f"无法检查用户名：\n{error}")
            return True
        return row is not None

    def _add_user(self) -> None:
        editor = UserEditor(self)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        if self._username_exists(editor.username()):
            QMessageBox.warning(self, "新增失败", "该用户名已存在。")
            return
        try:
            with self._connect() as conn:
                conn.execute(
                    "INSERT INTO TblUser (UserName, LoginPassword, UserClass) VALUES (?, ?, ?)",
                    (editor.username(), editor.password(), editor.user_class()),
                )
        except sqlite3.Error as error:
            QMessageBox.critical(self, "新增失败", f"无法新增用户：\n{error}")
            return
        self._load_users()

    def _edit_user(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        editor = UserEditor(self, user)
        if editor.exec() != QDialog.DialogCode.Accepted:
            return
        if self._username_exists(editor.username(), user.row_id):
            QMessageBox.warning(self, "保存失败", "该用户名已存在。")
            return

        values: tuple[object, ...]
        if editor.password():
            sql = """
                UPDATE TblUser
                SET UserName = ?, LoginPassword = ?, UserClass = ?
                WHERE rowid = ?
            """
            values = (editor.username(), editor.password(), editor.user_class(), user.row_id)
        else:
            sql = "UPDATE TblUser SET UserName = ?, UserClass = ? WHERE rowid = ?"
            values = (editor.username(), editor.user_class(), user.row_id)
        try:
            with self._connect() as conn:
                conn.execute(sql, values)
        except sqlite3.Error as error:
            QMessageBox.critical(self, "保存失败", f"无法更新用户：\n{error}")
            return
        self._load_users()

    def _delete_user(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        if user.username.lower() == "admin":
            QMessageBox.warning(self, "禁止删除", "内置 admin 管理员不能删除。")
            return
        current_user = str(self.runtime.get("current_user", "")).strip()
        if user.username == current_user:
            QMessageBox.warning(self, "禁止删除", "不能删除当前登录用户。")
            return
        answer = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除用户“{user.username}”吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            with self._connect() as conn:
                conn.execute("DELETE FROM TblUser WHERE rowid = ?", (user.row_id,))
        except sqlite3.Error as error:
            QMessageBox.critical(self, "删除失败", f"无法删除用户：\n{error}")
            return
        self._load_users()
