from __future__ import annotations

from datetime import datetime
from functools import partial
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction, QMouseEvent, QPixmap, QScreen
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import logging

from _runtime import get_runtime

logger = logging.getLogger(__name__)
from ui.view_login.view import Window as LoginWindow
from ui.wgt_tab.view import TabWidget


class FaultLabel(QLabel):
    double_clicked = Signal()

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
            event.accept()
            return
        super().mouseDoubleClickEvent(event)


class LogViewerDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None = None,
        logs_dir: Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.logs_dir = logs_dir or Path()
        self._current_path: Path | None = None
        self._current_raw_text: str = ""

        self.setWindowTitle("日志查看器")
        self.resize(960, 640)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        toolbar = QHBoxLayout()
        toolbar.addWidget(QLabel("日志文件:"))
        self._file_combo = QComboBox(self)
        self._file_combo.currentIndexChanged.connect(self._on_file_changed)
        toolbar.addWidget(self._file_combo, 1)

        self._full_log_check = QCheckBox("显示完整日志", self)
        self._full_log_check.stateChanged.connect(self._apply_filter)
        toolbar.addWidget(self._full_log_check)

        layout.addLayout(toolbar)

        self._path_label = QLabel(self)
        self._path_label.setWordWrap(True)
        layout.addWidget(self._path_label)

        self._editor = QPlainTextEdit(self)
        self._editor.setReadOnly(True)
        self._editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        layout.addWidget(self._editor, 1)

    def refresh_file_list(self) -> None:
        self._file_combo.blockSignals(True)
        self._file_combo.clear()
        if self.logs_dir.is_dir():
            log_files = sorted(
                [f for f in self.logs_dir.iterdir() if f.suffix == ".log" and f.is_file()],
                key=lambda x: x.name,
                reverse=True,
            )
            for log_file in log_files:
                self._file_combo.addItem(log_file.name, str(log_file))
        self._file_combo.blockSignals(False)

    def _on_file_changed(self, index: int) -> None:
        path_str = self._file_combo.itemData(index)
        if path_str:
            self.load_log(Path(path_str))

    def load_log(self, path: Path) -> None:
        self._current_path = path
        self._path_label.setText(f"日志:{path}")

        # 同步下拉列表选中状态
        index = self._file_combo.findData(str(path))
        if index >= 0:
            self._file_combo.blockSignals(True)
            self._file_combo.setCurrentIndex(index)
            self._file_combo.blockSignals(False)

        if not path.exists():
            self._current_raw_text = "今日日志不存在。"
            self._apply_filter()
            return

        self._current_raw_text = path.read_text(encoding="utf-8", errors="replace")
        self._apply_filter()

    def _apply_filter(self) -> None:
        if self._full_log_check.isChecked():
            filtered = self._current_raw_text
        else:
            lines = self._current_raw_text.splitlines()
            filtered_lines = [line for line in lines if "[INFO]" not in line]
            filtered = "\n".join(filtered_lines) if filtered_lines else "（无警告/错误级别日志记录）"

        self._editor.setPlainText(filtered)
        cursor = self._editor.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        self._editor.setTextCursor(cursor)


class Window(QMainWindow):
    runtime_event = Signal(dict)

    def __init__(
        self,
        *,
        menus: dict[str, list[dict[str, Any]]],
        views: dict[str, dict[str, Any]],
        default_view_id: str,
        title: str,
        current_user: str,
    ) -> None:
        super().__init__()
        self.menus = menus
        self.views = views
        self.default_view_id = default_view_id
        self.current_user = current_user
        self.runtime = get_runtime()
        self.size = self.runtime["size"]
        self.log_viewer: LogViewerDialog | None = None
        self._fault_message = "无"
        self._plc_ready = bool(getattr(self.runtime.get("plc"), "is_connected", lambda: False)())
        self._vsp_ready = bool(getattr(self.runtime.get("vsp"), "alive", False))
        self._ai_ready = False
        self._broker_subscriptions: list[object] = []
        self.runtime["current_user"] = current_user
        self.runtime.setdefault(
            "cur_user",
            {
                "username": current_user,
                "user_class": "SUPERUSER" if current_user.lower() == "admin" else "USER",
            },
        )
        self.runtime["status_sink"] = self.set_fault_message
        self.runtime_event.connect(self._apply_runtime_event)
        self.setWindowTitle(title)
        self._build_ui()
        self._apply_screen_size()
        self._create_toolbar()
        self.open_view(default_view_id, fixed=True)
        # 默认选中 default_view_id 对应的 tab
        default_index = self.tab_widget.find_view(default_view_id)
        if default_index >= 0:
            self.tab_widget.setCurrentIndex(default_index)
        self._subscribe_runtime_events()
        self._refresh_runtime_status()

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._shutdown_open_views()
        self._unsubscribe_runtime_events()
        super().closeEvent(event)

    def _shutdown_open_views(self) -> None:
        for index in range(self.tab_widget.count()):
            widget = self.tab_widget.widget(index)
            shutdown = getattr(widget, "shutdown", None)
            if callable(shutdown):
                shutdown()

    def _build_ui(self) -> None:
        central = QWidget(self)
        central.setObjectName("mainCentral")
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self.logo_card = QWidget(self)
        self.logo_card.setObjectName("frameLogoCard")
        logo_layout = QVBoxLayout(self.logo_card)
        logo_layout.setContentsMargins(8, 4, 8, 4)
        logo_layout.setSpacing(0)

        self.logo = QLabel(self.logo_card)
        self.logo.setObjectName("frameLogoImage")
        self.logo.setAlignment(Qt.AlignCenter)
        image_path = Path(self.runtime["base_dir"]) / "runtime" / "res" / "image" / "xlt.png"
        pixmap = QPixmap(str(image_path.resolve()))
        self.logo.setPixmap(pixmap.scaledToHeight(40, Qt.SmoothTransformation))
        logo_layout.addWidget(self.logo)
        layout.addWidget(self.logo_card)

        self.tab_widget = TabWidget(self)
        self.tab_widget.setObjectName("mainTabs")
        # 设置 size policy 为 Preferred，防止 TabWidget 撑大主窗口
        self.tab_widget.setSizePolicy(QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred))
        layout.addWidget(self.tab_widget, 1)

        self.footer = QWidget(self)
        self.footer.setObjectName("mainFooter")
        footer_layout = QHBoxLayout(self.footer)
        footer_layout.setContentsMargins(8, 4, 8, 4)
        footer_layout.setSpacing(8)

        self.plc_status_label = QLabel("PLC状态: 未知", self.footer)
        self.plc_status_label.setObjectName("statusStateLabel")
        self._set_status_label_state(self.plc_status_label, False)

        # self.vsp_status_label = QLabel("服务状态: 未知", self.footer)
        # self.vsp_status_label.setObjectName("statusStateLabel")
        # self._set_status_label_state(self.vsp_status_label, False)

        # self.ai_status_label = QLabel("AI服务状态: 未知", self.footer)
        # self.ai_status_label.setObjectName("statusStateLabel")
        # self._set_status_label_state(self.ai_status_label, False)

        self.fault_label = FaultLabel("故障信息: 无", self.footer)
        self.fault_label.setObjectName("faultText")
        self.fault_label.setMinimumWidth(280)
        self.fault_label.setToolTip("双击查看今日日志")
        self.fault_label.double_clicked.connect(self._open_today_log)

        footer_layout.addWidget(self.plc_status_label)
        # footer_layout.addWidget(self.vsp_status_label)
        # footer_layout.addWidget(self.ai_status_label)
        footer_layout.addWidget(self.fault_label, 1)

        # self.plc_dialog_button = QToolButton(self.footer)
        # self.plc_dialog_button.setObjectName("footerActionButton")
        # self.plc_dialog_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        # self.plc_dialog_button.setText("PLC操作")
        # self.plc_dialog_button.clicked.connect(self._open_plc_dialog)
        # footer_layout.addWidget(self.plc_dialog_button, 0, Qt.AlignRight)

        # self.dyn_dims_button = QToolButton(self.footer)
        # self.dyn_dims_button.setObjectName("footerActionButton")
        # self.dyn_dims_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        # self.dyn_dims_button.setText("实时数据")
        # self.dyn_dims_button.clicked.connect(self._open_dyn_dims_dialog)
        # footer_layout.addWidget(self.dyn_dims_button, 0, Qt.AlignRight)

        self.user_button = QToolButton(self.footer)
        self.user_button.setObjectName("currentUserButton")
        self.user_button.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.user_button.clicked.connect(self._switch_user)
        footer_layout.addWidget(self.user_button, 0, Qt.AlignRight)
        self._update_user_text()
        layout.addWidget(self.footer)

        self.setCentralWidget(central)
        self.ai_status_timer = QTimer(self)
        self.ai_status_timer.setInterval(10000)
        # self.ai_status_timer.timeout.connect(self._refresh_ai_status)
        self.ai_status_timer.start()

    def _set_status_label_state(self, label: QLabel, online: bool) -> None:
        label.setProperty("online", online)
        label.style().unpolish(label)
        label.style().polish(label)

    def _apply_screen_size(self) -> None:
        """根据配置文件设置窗口尺寸（固定尺寸，不受屏幕限制）"""
        w, h = self.size
        self.resize(w, h)
        self.setFixedSize(w, h)

        screens = QApplication.instance().screens()
        if not screens:
            return
        screen = screens[0].availableGeometry()
        self.move(
            (screen.width() - w) // 2,
            (screen.height() - h) // 2
        )

    def _create_status_led(self, parent: QWidget) -> QFrame:
        led = QFrame(parent)
        led.setFixedSize(10, 10)
        led.setProperty("online", False)
        led.style().unpolish(led)
        led.style().polish(led)
        return led

    def _set_led_state(self, led: QFrame, online: bool) -> None:
        led.setProperty("online", online)
        led.style().unpolish(led)
        led.style().polish(led)

    def _create_toolbar(self) -> None:
        toolbar = QToolBar("menu", self)
        toolbar.setObjectName("mainToolbar")
        toolbar.setMovable(False)
        toolbar.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(Qt.TopToolBarArea, toolbar)

        for group_name, actions in self.menus.items():
            button = QToolButton(self)
            button.setText(group_name)
            button.setPopupMode(QToolButton.InstantPopup)
            for action_config in actions:
                action = QAction(action_config["title"], self)
                action.triggered.connect(
                    partial(
                        self.dispatch_action,
                        action_config["view_id"],
                        action_config.get("pop", False),
                        action_config.get("fixed", False),
                        action_config.get("admin", False),
                    )
                )
                button.addAction(action)
            toolbar.addWidget(button)

    def _update_user_text(self) -> None:
        self.user_button.setText(f"当前用户: {self.current_user}")

    def _switch_user(self) -> None:
        login_window = LoginWindow()
        login_window.set_selected_username(self.current_user)
        if login_window.exec() != QDialog.Accepted:
            return
        self.current_user = login_window.username
        self.runtime["current_user"] = self.current_user
        self.runtime["cur_user"] = {
            "username": login_window.username,
            "user_class": login_window.user_class,
        }
        self._update_user_text()
        broker = self.runtime.get("broker")
        if broker:
            broker.publish(topic="user_changed", msg={"user": self.runtime["cur_user"]})

    def _open_today_log(self) -> None:
        logs_dir = Path(self.runtime["base_dir"]) / "logs" / "daily"
        if self.log_viewer is None:
            self.log_viewer = LogViewerDialog(self, logs_dir=logs_dir)
        self.log_viewer.refresh_file_list()
        self.log_viewer.load_log(self._today_log_path())
        self.log_viewer.show()
        self.log_viewer.raise_()
        self.log_viewer.activateWindow()

    def _today_log_path(self) -> Path:
        logs_path = Path(self.runtime["base_dir"]) /  "logs" / "daily"
        if logs_path.is_dir():
            return logs_path / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        return logs_path

    def set_fault_message(self, *, fault_message: str) -> None:
        self._fault_message = fault_message or "无"
        self._render_footer_status()

    def update_footer_status(self, *, plc_ready: bool, vsp_ready: bool, fault_message: str) -> None:
        self._plc_ready = plc_ready
        # self._vsp_ready = vsp_ready
        self._fault_message = fault_message or "无"
        self._render_footer_status()

    def _render_footer_status(self) -> None:
        self._set_status_label_state(self.plc_status_label, self._plc_ready)
        self.plc_status_label.setText("PLC在线" if self._plc_ready else "PLC离线")
        # self.plc_dialog_button.setEnabled(self._plc_ready)

        # self._set_status_label_state(self.vsp_status_label, self._vsp_ready)
        # self.dyn_dims_button.setEnabled(self._vsp_ready)
        # self.vsp_status_label.setText("传感器在线" if self._vsp_ready else "传感器离线")

        # self.ai_status_label.setText("AI服务在线" if self._ai_ready else "AI服务离线")
        self.fault_label.setText(f"故障信息: {self._fault_message}")

    def _refresh_runtime_status(self) -> None:
        self._plc_ready = bool(getattr(self.runtime.get("plc"), "is_connected", lambda: False)())
        # self._vsp_ready = bool(getattr(self.runtime["vsp"], "alive", False))
        # self._refresh_ai_status(render=False)
        self._render_footer_status()

    def _refresh_ai_status(self, *, render: bool = True) -> None:
        # self._ai_ready = check_ollama_status()
        if render:
            self._render_footer_status()

    def _subscribe_runtime_events(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            return
        self._broker_subscriptions = [
            broker.subscribe("plc_poll", self._on_plc_poll),
            # broker.subscribe("vsp_poll", self._on_vsp_poll),
            broker.subscribe("pt_error", self._on_pt_error),
            broker.subscribe("node_wait", self._on_node_wait),
            broker.subscribe("msg_guard", self._on_guard_check),
            broker.subscribe("switch_tab", self._on_switch_tab),
        ]

    def _unsubscribe_runtime_events(self) -> None:
        broker = self.runtime.get("broker")
        if broker is None:
            self._broker_subscriptions.clear()
            return
        for subscription in self._broker_subscriptions:
            broker.unsubscribe(subscription)
        self._broker_subscriptions.clear()

    def _on_plc_poll(self, **payload) -> None:
        self.runtime_event.emit({"topic": "plc_poll", **payload})

    def _on_vsp_poll(self, **payload) -> None:
        self.runtime_event.emit({"topic": "vsp_poll", **payload})

    def _on_pt_error(self, **payload) -> None:
        self.runtime_event.emit({"topic": "pt_error", **payload})

    def _on_node_wait(self, **payload) -> None:
        pass

    def _on_guard_check(self, **payload) -> None:
        self.runtime_event.emit({"topic": "msg_guard", **payload})

    def _on_switch_tab(self, **payload) -> None:
        self.runtime_event.emit({"topic": "switch_tab", **payload})

    def _apply_runtime_event(self, payload: dict[str, Any]) -> None:
        topic = payload.get("topic")

        if topic == "plc_poll":
            self._plc_ready = bool(payload.get("alive"))

        elif topic == "vsp_poll":
            self._vsp_ready = bool(payload.get("alive"))


        elif topic == "pt_error":
            pt_name = str(payload.get("pt_name") or "").strip()
            info = str(payload.get("info") or "").strip()
            error = str(payload.get("error") or "").strip()
            message_parts = [part for part in (pt_name, info, error) if part]
            self._fault_message = " | ".join(message_parts) if message_parts else "PLC错误"

        elif topic == "msg_guard":
            risks = payload.get("risks")
            for risk in risks:
                logger.warning(f"安全风险[{risk.name}][{risk.level}]:{risk.message}")
                if risk.level=="HIGH":
                    plc = self.runtime.get("plc")
                    if plc is not None:
                        plc._emc_stop()

        elif topic == "switch_tab":
            tab_id = payload.get("tab")
            if tab_id in self.views:
                self.open_view(tab_id, fixed=False)
            return

        else:
            return
        self._render_footer_status()

    def _is_admin_user(self) -> bool:
        cur_user = self.runtime.get("cur_user")
        if isinstance(cur_user, dict):
            username = str(cur_user.get("username", "")).strip().lower()
            user_class = str(cur_user.get("user_class", "")).strip().upper()
            return username == "admin" or user_class in {"SUPERUSER", "ADMIN"}
        current_user = str(self.runtime.get("current_user", self.current_user)).strip().lower()
        return current_user == "admin"

    def dispatch_action(self, view_id: str, pop: bool, fixed: bool, admin: bool = False) -> None:
        if view_id not in self.views:
            QMessageBox.warning(self, "未注册页面", f"页面 {view_id} 未在注册中心声明。")
            return
        if admin and not self._is_admin_user():
            QMessageBox.warning(self, "权限不足", "当前页面仅允许管理员打开。")
            return
        if pop:
            dialog = self.views[view_id]["obj"]()
            dialog.setWindowTitle(self.views[view_id]["title"])
            dialog.exec()
            return
        self.open_view(view_id, fixed=fixed)

    def open_view(self, view_id: str, *, fixed: bool) -> None:
        existing_index = self.tab_widget.find_view(view_id)
        if existing_index != -1:
            self.tab_widget.setCurrentIndex(existing_index)
            return
        widget = self.views[view_id]["obj"]()
        self.tab_widget.create_tab(
            widget=widget,
            title=self.views[view_id]["title"],
            view_id=view_id,
            fixed=fixed,
        )
