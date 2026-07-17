from __future__ import annotations

import sys


def main() -> int:
    if sys.platform != "win32":
        print("此程序仅支持 Windows 10/11。核心测试可在其他系统运行。", file=sys.stderr)
        return 1

    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QMessageBox

        from .capture import enable_dpi_awareness
        from .storage import DataStore
        from .ui import OverlayWindow
    except ImportError as error:
        print(f"缺少运行依赖：{error}\n请先执行 python -m pip install -r requirements.txt", file=sys.stderr)
        return 2

    enable_dpi_awareness()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("洛克王国异色保底计数")
    app.setOrganizationName("RockKingdomShinyCounter")

    try:
        window = OverlayWindow(DataStore())
        window.show()
    except Exception as error:  # Final startup boundary for a desktop app.
        QMessageBox.critical(None, "启动失败", str(error))
        return 3
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

