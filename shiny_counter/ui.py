from __future__ import annotations

import ctypes
import sys
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QCloseEvent, QMouseEvent
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from .capture import CaptureError, Win32Capture, WindowInfo, list_visible_windows
from .hotkeys import GlobalHotkeyThread
from .model import HistoryEvent
from .storage import AppData, DataStore
from .worker import RecognitionWorker


APP_STYLE = """
QWidget#overlay {
    background: #172033;
    color: #ffffff;
    border: 1px solid #52617d;
    border-radius: 12px;
}
QLabel { color: #ffffff; }
QLabel#count { font-size: 38px; font-weight: 700; color: #55e6ff; }
QLabel#target { font-size: 15px; font-weight: 700; color: #ffd166; }
QLabel#status { color: #dbeafe; font-size: 11px; font-weight: 600; }
QPushButton {
    background: #293852;
    color: #ffffff;
    border: 1px solid #52617d;
    border-radius: 6px;
    padding: 5px 8px;
}
QPushButton:hover { background: #354a6d; }
QProgressBar {
    border: 1px solid #52617d;
    border-radius: 5px;
    background: #101728;
    text-align: center;
    color: white;
}
QProgressBar::chunk { background: #3aa7dc; border-radius: 4px; }
"""


class WindowPickerDialog(QDialog):
    def __init__(self, windows: list[WindowInfo], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("选择洛克王国窗口")
        self.resize(560, 360)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("请选择正在运行游戏的窗口："))
        self.list_widget = QListWidget()
        for window in windows:
            item = QListWidgetItem(f"{window.title}    {window.width}×{window.height}")
            item.setData(Qt.ItemDataRole.UserRole, window)
            self.list_widget.addItem(item)
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        self.list_widget.itemDoubleClicked.connect(lambda _: self.accept())
        layout.addWidget(self.list_widget)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_window(self) -> WindowInfo | None:
        item = self.list_widget.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None


class SettingsDialog(QDialog):
    def __init__(self, data: AppData, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.data = data
        self.setWindowTitle("计数器设置")
        self.resize(540, 580)
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self.target = QLineEdit(data.counter.target_name)
        self.pity = QSpinBox()
        self.pity.setRange(1, 1_000_000)
        self.pity.setValue(data.counter.pity_limit)
        self.ocr_keywords = QLineEdit("，".join(data.settings.ocr_keywords))
        self.ocr_keywords.setPlaceholderText("例如：写进了童话里")
        self.ocr_confidence = QDoubleSpinBox()
        self.ocr_confidence.setRange(0.10, 1.0)
        self.ocr_confidence.setDecimals(2)
        self.ocr_confidence.setSingleStep(0.05)
        self.ocr_confidence.setValue(data.settings.ocr_min_confidence)
        self.ocr_interval = QSpinBox()
        self.ocr_interval.setRange(200, 5000)
        self.ocr_interval.setSingleStep(100)
        self.ocr_interval.setSuffix(" ms")
        self.ocr_interval.setValue(data.settings.ocr_interval_ms)
        self.opacity = QDoubleSpinBox()
        self.opacity.setRange(0.30, 1.0)
        self.opacity.setDecimals(2)
        self.opacity.setSingleStep(0.05)
        self.opacity.setValue(data.settings.opacity)
        form.addRow("目标名称", self.target)
        form.addRow("保底次数", self.pity)
        form.addRow("OCR 关键词", self.ocr_keywords)
        form.addRow("OCR 最低置信度", self.ocr_confidence)
        form.addRow("OCR 扫描间隔", self.ocr_interval)
        form.addRow("悬浮窗透明度", self.opacity)
        layout.addLayout(form)

        hotkey_group = QGroupBox("全局快捷键")
        hotkey_form = QFormLayout(hotkey_group)
        self.hotkeys: dict[str, QLineEdit] = {}
        labels = {
            "toggle_click_through": "切换点击穿透",
            "increment": "手动补一",
            "undo": "撤销",
            "pause": "暂停或继续",
        }
        for action, label in labels.items():
            edit = QLineEdit(data.settings.hotkeys.get(action, ""))
            self.hotkeys[action] = edit
            hotkey_form.addRow(label, edit)
        layout.addWidget(hotkey_group)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _validate_and_accept(self) -> None:
        if not self.target.text().strip():
            QMessageBox.warning(self, "设置无效", "目标名称不能为空。")
            return
        keywords = self.ocr_keywords.text().replace("，", ",").split(",")
        if not any(keyword.strip() for keyword in keywords):
            QMessageBox.warning(self, "设置无效", "至少填写一个只在结算画面出现的 OCR 关键词。")
            return
        self.accept()

    def apply(self) -> None:
        self.data.counter.target_name = self.target.text().strip()
        self.data.counter.pity_limit = self.pity.value()
        self.data.counter.pity_reached = self.data.counter.count >= self.data.counter.pity_limit
        self.data.settings.ocr_keywords = [
            keyword.strip()
            for keyword in self.ocr_keywords.text().replace("，", ",").split(",")
            if keyword.strip()
        ]
        self.data.settings.ocr_min_confidence = self.ocr_confidence.value()
        self.data.settings.ocr_interval_ms = self.ocr_interval.value()
        self.data.settings.opacity = self.opacity.value()
        self.data.settings.hotkeys = {action: edit.text().strip() for action, edit in self.hotkeys.items()}


class HistoryDialog(QDialog):
    def __init__(self, history: list[HistoryEvent], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("计数历史")
        self.resize(760, 440)
        layout = QVBoxLayout(self)
        table = QTableWidget(0, 6)
        table.setHorizontalHeaderLabels(["时间", "事件", "来源", "变更前", "变更后", "置信度"])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        names = {
            "increment": "加一",
            "undo": "撤销",
            "reset": "重置",
            "pity_reached": "达到保底",
        }
        for event in reversed(history):
            row = table.rowCount()
            table.insertRow(row)
            values = [
                event.at.replace("T", " ")[:19],
                names.get(event.type, event.type),
                event.source,
                str(event.before),
                str(event.after),
                "" if event.score is None else f"{event.score:.3f}",
            ]
            for column, value in enumerate(values):
                table.setItem(row, column, QTableWidgetItem(value))
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class OCRTextDialog(QDialog):
    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("最近一次横幅 OCR 结果")
        self.resize(640, 420)
        layout = QVBoxLayout(self)
        hint = QLabel("从下列文字中选择只在有效结算画面出现的短语，并填入设置中的 OCR 关键词。")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        editor = QPlainTextEdit()
        editor.setReadOnly(True)
        editor.setPlainText(text or "尚无 OCR 结果。请先选择游戏窗口并等待一次扫描。")
        layout.addWidget(editor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class OverlayWindow(QWidget):
    def __init__(self, store: DataStore) -> None:
        super().__init__()
        self.store = store
        self.data = store.load()
        self.recognition_worker: RecognitionWorker | None = None
        self.hotkey_worker: GlobalHotkeyThread | None = None
        self.paused = False
        self.drag_offset: QPoint | None = None
        self.last_ocr_text = ""

        self.setObjectName("overlay")
        self.setWindowTitle("洛克王国异色保底计数")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(APP_STYLE)
        self.setFixedWidth(350)
        self._build_ui()
        self._restore_window_state()
        self._refresh_display()
        self._start_hotkeys()
        self._restart_recognition()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 12, 16, 14)
        outer.setSpacing(8)

        header = QHBoxLayout()
        self.target_label = QLabel()
        self.target_label.setObjectName("target")
        header.addWidget(self.target_label, 1)
        close_button = QPushButton("×")
        close_button.setFixedSize(28, 24)
        close_button.clicked.connect(self.close)
        header.addWidget(close_button)
        outer.addLayout(header)

        self.count_label = QLabel()
        self.count_label.setObjectName("count")
        self.count_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.count_label)
        self.remaining_label = QLabel()
        self.remaining_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.remaining_label)
        self.progress = QProgressBar()
        outer.addWidget(self.progress)

        primary = QHBoxLayout()
        increment_button = QPushButton("补一")
        increment_button.clicked.connect(self._manual_increment)
        undo_button = QPushButton("撤销")
        undo_button.clicked.connect(self._undo)
        self.pause_button = QPushButton("暂停")
        self.pause_button.clicked.connect(self._toggle_pause)
        reset_button = QPushButton("重置")
        reset_button.clicked.connect(self._reset)
        for button in (increment_button, undo_button, self.pause_button, reset_button):
            primary.addWidget(button)
        outer.addLayout(primary)

        for actions in (
            [("选窗口", self._select_window), ("设置", self._open_settings), ("历史", self._open_history)],
            [("查看文字", self._show_ocr_text), ("导入", self._import_data), ("导出", self._export_data)],
        ):
            row = QHBoxLayout()
            for label, handler in actions:
                button = QPushButton(label)
                button.clicked.connect(handler)
                row.addWidget(button)
            outer.addLayout(row)

        self.status_label = QLabel("准备中")
        self.status_label.setObjectName("status")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(self.status_label)

    def _restore_window_state(self) -> None:
        self.setWindowOpacity(self.data.settings.opacity)
        if self.data.settings.overlay_position is not None:
            self.move(*self.data.settings.overlay_position)
        else:
            screen = QApplication.primaryScreen().availableGeometry()
            self.move(screen.right() - self.width() - 24, screen.top() + 80)
        # Always start interactable so a changed or occupied hotkey cannot trap the overlay.
        self._set_click_through(False, persist=False)

    def showEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().showEvent(event)
        if sys.platform == "win32":
            try:
                ctypes.windll.user32.SetWindowDisplayAffinity(int(self.winId()), 0x00000000)
            except (AttributeError, OSError):
                pass

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self.drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_offset)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.drag_offset is not None:
            self.drag_offset = None
            self.data.settings.overlay_position = (self.x(), self.y())
            self._save()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.data.settings.overlay_position = (self.x(), self.y())
        self._save()
        self._stop_recognition()
        self._stop_hotkeys()
        event.accept()

    def _save(self) -> None:
        try:
            self.store.save(self.data)
        except OSError as error:
            self.status_label.setText(f"保存失败：{error}")

    def _refresh_display(self) -> None:
        counter = self.data.counter
        self.target_label.setText(counter.target_name)
        self.count_label.setText(f"{counter.count} / {counter.pity_limit}")
        self.remaining_label.setText("已达到保底，请确认后手动重置" if counter.pity_reached else f"距离保底还差 {counter.remaining} 次")
        self.progress.setRange(0, counter.pity_limit)
        self.progress.setValue(min(counter.count, counter.pity_limit))
        if counter.pity_reached:
            self.count_label.setStyleSheet("color: #ffd166;")
            self.progress.setStyleSheet("QProgressBar::chunk { background: #e3a52b; }")
        else:
            self.count_label.setStyleSheet("")
            self.progress.setStyleSheet("")

    def _increment(self, source: str, score: float | None = None) -> None:
        reached_now = self.data.counter.increment(source=source, score=score)
        self._save()
        self._refresh_display()
        if reached_now:
            QApplication.alert(self, 4000)
            if sys.platform == "win32":
                import winsound

                winsound.MessageBeep(winsound.MB_ICONEXCLAMATION)

    def _manual_increment(self) -> None:
        self._increment("manual")

    def _auto_increment(self, score: float) -> None:
        self._increment("auto", score)

    def _undo(self) -> None:
        if self.data.counter.undo():
            self._save()
            self._refresh_display()

    def _reset(self) -> None:
        answer = QMessageBox.question(
            self,
            "确认重置",
            f"确定将当前 {self.data.counter.count} 次计数清零吗？历史记录会保留。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.data.counter.reset()
            self._save()
            self._refresh_display()

    def _toggle_pause(self) -> None:
        self.paused = not self.paused
        self.pause_button.setText("继续" if self.paused else "暂停")
        if self.recognition_worker is not None:
            self.recognition_worker.set_paused(self.paused)
        if not self.paused:
            self.status_label.setText("正在恢复识别")

    def _set_click_through(self, enabled: bool, *, persist: bool = True) -> None:
        self.data.settings.click_through = enabled
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
        self.show()
        if persist:
            self._save()
        if enabled:
            hotkey = self.data.settings.hotkeys.get("toggle_click_through", "")
            self.status_label.setText(f"点击穿透已开启，按 {hotkey} 关闭")

    def _toggle_click_through(self) -> None:
        self._set_click_through(not self.data.settings.click_through)

    def _recognition_status(self, message: str, score: float) -> None:
        if score >= 0:
            self.status_label.setText(f"{message}，置信度 {score:.3f}")
        else:
            self.status_label.setText(message)

    def _stop_recognition(self) -> None:
        if self.recognition_worker is not None:
            self.recognition_worker.requestInterruption()
            if not self.recognition_worker.wait(5000):
                self.recognition_worker.terminate()
                self.recognition_worker.wait(2000)
            self.recognition_worker = None

    def _restart_recognition(self) -> None:
        self._stop_recognition()
        settings = self.data.settings
        if not settings.window_title or settings.client_size is None:
            self.status_label.setText("请先点击“选窗口”选择游戏客户端")
            return
        worker = RecognitionWorker(settings, self.store.root)
        worker.detected.connect(self._auto_increment)
        worker.status_changed.connect(self._recognition_status)
        worker.ocr_text_changed.connect(self._remember_ocr_text)
        worker.stopped_with_error.connect(self.status_label.setText)
        worker.set_paused(self.paused)
        self.recognition_worker = worker
        worker.start()

    def _stop_hotkeys(self) -> None:
        if self.hotkey_worker is not None:
            self.hotkey_worker.requestInterruption()
            self.hotkey_worker.wait(1500)
            self.hotkey_worker = None

    def _start_hotkeys(self) -> None:
        self._stop_hotkeys()
        worker = GlobalHotkeyThread(self.data.settings.hotkeys)
        worker.activated.connect(self._handle_hotkey)
        worker.registration_error.connect(self._hotkey_error)
        self.hotkey_worker = worker
        worker.start()

    def _handle_hotkey(self, action: str) -> None:
        handlers = {
            "toggle_click_through": self._toggle_click_through,
            "increment": self._manual_increment,
            "undo": self._undo,
            "pause": self._toggle_pause,
        }
        handler = handlers.get(action)
        if handler is not None:
            handler()

    def _hotkey_error(self, message: str) -> None:
        self.status_label.setText(message)
        QMessageBox.warning(self, "全局快捷键不可用", f"{message}\n请在设置中更换快捷键。")

    def _select_window(self) -> None:
        windows = [window for window in list_visible_windows() if window.title != self.windowTitle()]
        if not windows:
            QMessageBox.warning(self, "没有可选窗口", "请先启动洛克王国客户端并保持窗口可见。")
            return
        picker = WindowPickerDialog(windows, self)
        if picker.exec() != QDialog.DialogCode.Accepted:
            return
        selected = picker.selected_window()
        if selected is None:
            return

        capture: Win32Capture | None = None
        try:
            capture = Win32Capture(selected.title)
            _, client_size = capture.capture_client()
        except CaptureError as error:
            QMessageBox.critical(self, "截图失败", str(error))
            return
        finally:
            if capture is not None:
                capture.close()
        self.data.settings.window_title = selected.title
        self.data.settings.client_size = client_size
        self._save()
        self._restart_recognition()
        self.status_label.setText("窗口已选择，正在启动横幅 OCR")

    def _remember_ocr_text(self, text: str) -> None:
        self.last_ocr_text = text

    def _show_ocr_text(self) -> None:
        OCRTextDialog(self.last_ocr_text, self).exec()

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.data, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            dialog.apply()
            self.setWindowOpacity(self.data.settings.opacity)
            self._save()
            self._refresh_display()
            self._start_hotkeys()
            self._restart_recognition()

    def _open_history(self) -> None:
        HistoryDialog(self.data.counter.history, self).exec()

    def _export_data(self) -> None:
        default_name = f"异色计数备份-{datetime.now():%Y%m%d-%H%M%S}.zip"
        path, _ = QFileDialog.getSaveFileName(self, "导出计数数据", default_name, "ZIP 文件 (*.zip)")
        if not path:
            return
        try:
            self._save()
            self.store.export_archive(Path(path))
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "导出失败", str(error))
            return
        self.status_label.setText(f"已导出到 {path}")

    def _import_data(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入计数数据", "", "ZIP 文件 (*.zip)")
        if not path:
            return
        answer = QMessageBox.question(
            self,
            "确认导入",
            "导入会替换当前计数与设置，并自动备份当前数据。是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            self.store.import_archive(Path(path))
            self.data = self.store.load()
        except (OSError, ValueError) as error:
            QMessageBox.critical(self, "导入失败", str(error))
            return
        self.setWindowOpacity(self.data.settings.opacity)
        self._refresh_display()
        self._start_hotkeys()
        self._restart_recognition()
        self.status_label.setText("导入完成")

