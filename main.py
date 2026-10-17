from __future__ import annotations

import configparser
import logging
import sys
from pathlib import Path


BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent

for import_path in (BASE_DIR, BASE_DIR / "libs"):
    text = str(import_path)
    if text not in sys.path:
        sys.path.insert(0, text)

from PySide6.QtWidgets import QApplication, QDialog

from _runtime import get_runtime, update_runtime
from logger import configure_application_logging
from ui.theme import apply_theme
from ui.registry import load_ui_registry
from ui.view_frame.view import Window as MainFrame
from ui.view_login.view import Window as LoginWindow


configure_application_logging(BASE_DIR)
logger = logging.getLogger(__name__)


def _load_runtime() -> dict[str, object]:
    import broker as broker_lib
    import vsp as vsp_lib
    from broker import create_broker
    from vsp import load_vsp
    import pdf as pdf_lib
    from dbstore import init_db

    _rt = get_runtime()
    init_db(str(_rt["paths"]["db"]))
    broker = create_broker()
    sim=_rt['sim']=='true'

    if _rt["config"].getboolean("vsp", "used"):
        vsp_table = load_vsp(str(_rt["paths"]["vsp_config"]))
        vsp_table.broker = broker
        vsp_table.start()

    ui_registry = load_ui_registry()

    # 初始化 PDF 报告生成器
    pdf_report = pdf_lib.PdfReport(
        template_path=str(_rt["paths"]["report_template"]),
        output_dir=str(_rt["paths"]["report_path"])
    )

    runtime = update_runtime(
        broker_lib=broker_lib,

        vsp_lib=vsp_lib if _rt["config"].getboolean("vsp", "used") else None,
        vsp=vsp_table  if _rt["config"].getboolean("vsp", "used") else None,

        pdf_lib=pdf_lib,
        broker=broker,
        ui_registry=ui_registry,
        pdf_report=pdf_report,
    )
    return runtime


def main() -> int:
    runtime = _load_runtime()
    logger.info(f"============ 程序启动 ============")
    logger.info(f"初始化运行时")

    def _handle_exception(exc_type, exc_value, exc_traceback) -> None:
        logger.exception("未知异常", exc_info=(exc_type, exc_value, exc_traceback))
        sys.__excepthook__(exc_type, exc_value, exc_traceback)

    sys.excepthook = _handle_exception

    app = QApplication(sys.argv)
    cleanup_done = False

    def _stop_pollers() -> None:
        nonlocal cleanup_done
        if cleanup_done:
            return
        cleanup_done = True

        vsp = runtime.get("vsp")
        if vsp is not None:
            logger.info(f"关闭VSP轮询")
            try:
                vsp.stop()
            except Exception:
                logger.exception("stop vsp polling failed")

        broker = runtime.get("broker")
        if broker is not None:
            try:
                broker.clear()
            except Exception:
                logger.exception("clear broker failed")
        logger.info(f"============ 程序退出 ============")

    app.aboutToQuit.connect(_stop_pollers)
    apply_theme(app, runtime["theme"])
    try:
        login_window = LoginWindow()
        if login_window.exec() != QDialog.Accepted:
            logger.info(f"取消登录")
            return 0

        ui_registry = runtime["ui_registry"]
        main_window = MainFrame(
            menus=ui_registry["menus"],
            views=ui_registry["views"],
            default_view_id=ui_registry["default_view_id"],
            title=ui_registry["window_title"],
            current_user=login_window.username,
        )
        main_window.show()
        return app.exec()
    finally:
        _stop_pollers()


if __name__ == "__main__":
    sys.exit(main())
