#!/usr/bin/env python3
"""MultiTimer - 多路倒计时小工具

特性:
- GUI (PySide6), 窗口置顶, 随时可见
- 输入 label + 点击预设时间即开始一个倒计时, 可同时跑多个
- 预设 (1min / 5min ...) 可自行增删改, 本地持久化
- 倒计时结束发送 macOS 通知 (osascript), 无声音
- 预设与正在运行的倒计时状态本地保存, 关掉再打开会恢复
- 倒计时结束后自动从列表移除
"""

import json
import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

APP_NAME = "MultiTimer"
STATE_PATH = Path.home() / ".config" / "multitimer" / "state.json"
WINDOW_WIDTH = 250
DEFAULT_PRESETS = [
    {"name": "1min", "seconds": 60},
    {"name": "5min", "seconds": 300},
    {"name": "10min", "seconds": 600},
    {"name": "15min", "seconds": 900},
    {"name": "30min", "seconds": 1800},
]

STYLE = """
QWidget { font-size: 12px; color: #2b2b30; }
#Card { background: #fbfbfd; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
#timerRow { background: #ffffff; border: 1px solid #ececf0; border-radius: 8px; }
QLineEdit {
    border: 1px solid #d5d5da; border-radius: 7px;
    padding: 5px 8px; background: #ffffff;
}
QLineEdit:focus { border: 1px solid #0a84ff; }
QDoubleSpinBox {
    border: 1px solid #d5d5da; border-radius: 7px;
    padding: 3px 4px; background: #ffffff; color: #2b2b30;
}
QPushButton {
    border: none; border-radius: 7px; padding: 5px 6px; background: #eceef2;
}
QPushButton:hover { background: #e2e5ec; }
QPushButton:pressed { background: #d5d9e2; }
QPushButton#preset { background: #0a84ff; color: #ffffff; font-weight: 600; }
QPushButton#preset:hover { background: #0a78e6; }
QPushButton#preset:pressed { background: #0a6ccc; }
QPushButton#ghost { background: transparent; color: #8a8a90; padding: 2px; }
QPushButton#ghost:hover { color: #d9534f; }
#caption { color: #9a9aa0; font-size: 11px; }
QProgressBar {
    border: none; border-radius: 3px; background: #e6e6eb;
    max-height: 5px; min-height: 5px;
}
QProgressBar::chunk { border-radius: 3px; background: #0a84ff; }
"""


def fmt_remaining(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds % 60 == 0:
        return f"{seconds // 60}min"
    return fmt_remaining(seconds)


_NOTIFY_SCRIPT = (
    "on run argv\n"
    "  display notification (item 3 of argv) "
    "with title (item 1 of argv) subtitle (item 2 of argv)\n"
    "end run"
)


def send_notification(title: str, subtitle: str, message: str) -> None:
    """通过 osascript 发送 macOS 通知 (不带 sound => 静音)。

    参数以 argv 形式传入 AppleScript, 避免任务名含引号等特殊字符时出错或被注入。
    """
    try:
        subprocess.Popen(
            ["osascript", "-e", _NOTIFY_SCRIPT, title, subtitle, message],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 持久化
# ---------------------------------------------------------------------------
def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"presets": [dict(p) for p in DEFAULT_PRESETS], "timers": []}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {"presets": [dict(p) for p in DEFAULT_PRESETS], "timers": []}
    presets = data.get("presets") or [dict(p) for p in DEFAULT_PRESETS]
    now = time.time()
    timers = [t for t in data.get("timers", []) if t.get("end_ts", 0) > now]
    return {"presets": presets, "timers": timers}


def save_state(presets: list, timers: list) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "presets": presets,
        "timers": [
            {"id": t["id"], "label": t["label"], "end_ts": t["end_ts"], "duration": t["duration"]}
            for t in timers
        ],
    }
    STATE_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------------------
# 预设编辑对话框
# ---------------------------------------------------------------------------
class PresetEditor(QDialog):
    def __init__(self, presets: list, parent=None):
        super().__init__(parent)
        self.setWindowTitle("编辑预设")
        self.setMinimumWidth(320)
        self._rows = []

        outer = QVBoxLayout(self)
        hint = QLabel("名称显示在按钮上, 时长单位为分钟。")
        hint.setStyleSheet("color: gray;")
        outer.addWidget(hint)

        self.rows_layout = QVBoxLayout()
        outer.addLayout(self.rows_layout)

        add_btn = QPushButton("+ 添加预设")
        add_btn.clicked.connect(lambda: self._add_row("", 5.0))
        outer.addWidget(add_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        outer.addWidget(buttons)

        for p in presets:
            self._add_row(p["name"], p["seconds"] / 60.0)

    def _add_row(self, name: str, minutes: float):
        row = QWidget()
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)

        name_edit = QLineEdit(name)
        name_edit.setPlaceholderText("名称, 如 5min")

        min_spin = QDoubleSpinBox()
        min_spin.setRange(0.1, 1440.0)
        min_spin.setDecimals(1)
        min_spin.setSingleStep(1.0)
        min_spin.setSuffix(" 分钟")
        min_spin.setValue(minutes)

        del_btn = QPushButton("删除")

        layout.addWidget(name_edit, 2)
        layout.addWidget(min_spin, 1)
        layout.addWidget(del_btn)

        entry = {"widget": row, "name": name_edit, "min": min_spin}
        self._rows.append(entry)
        del_btn.clicked.connect(lambda: self._remove_row(entry))
        self.rows_layout.addWidget(row)

    def _remove_row(self, entry):
        self._rows.remove(entry)
        entry["widget"].setParent(None)
        entry["widget"].deleteLater()

    def result_presets(self) -> list:
        presets = []
        for e in self._rows:
            name = e["name"].text().strip()
            seconds = int(round(e["min"].value() * 60))
            if name and seconds > 0:
                presets.append({"name": name, "seconds": seconds})
        return presets


# ---------------------------------------------------------------------------
# 单个倒计时行
# ---------------------------------------------------------------------------
class TimerRow(QFrame):
    def __init__(self, timer: dict, on_cancel):
        super().__init__()
        self.timer = timer
        self.duration = max(1, int(timer["duration"]))
        self._full_label = timer["label"]
        self.setObjectName("timerRow")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(9, 6, 8, 7)
        layout.setSpacing(5)

        top = QHBoxLayout()
        top.setSpacing(6)
        self.label = QLabel()
        self.label.setToolTip(self._full_label)
        fm = QFontMetrics(self.label.font())
        self.label.setText(fm.elidedText(self._full_label, Qt.ElideMiddle, WINDOW_WIDTH - 90))

        self.remaining = QLabel("--:--")
        self.remaining.setFont(QFont("Menlo", 12))
        self.remaining.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        cancel_btn = QPushButton("✕")
        cancel_btn.setObjectName("ghost")
        cancel_btn.setFixedWidth(18)
        cancel_btn.setToolTip("取消该倒计时")
        cancel_btn.clicked.connect(lambda: on_cancel(timer))

        top.addWidget(self.label, 1)
        top.addWidget(self.remaining)
        top.addWidget(cancel_btn)
        layout.addLayout(top)

        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setTextVisible(False)
        layout.addWidget(self.bar)

    def update_remaining(self, seconds: float):
        self.remaining.setText(fmt_remaining(seconds))
        frac = max(0.0, min(1.0, seconds / self.duration))
        self.bar.setValue(int(frac * 1000))
        if seconds <= 10:
            self.remaining.setStyleSheet("color: #d9534f;")
            self.bar.setStyleSheet("QProgressBar::chunk { border-radius: 3px; background: #d9534f; }")
        else:
            self.remaining.setStyleSheet("")
            self.bar.setStyleSheet("")


# ---------------------------------------------------------------------------
# 主窗口
# ---------------------------------------------------------------------------
class MultiTimer(QWidget):
    def __init__(self):
        super().__init__()
        state = load_state()
        self.presets = state["presets"]
        self.timers = []  # {id, label, end_ts, duration, row}

        self.setWindowTitle(APP_NAME)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setObjectName("Card")
        self.setStyleSheet(STYLE)
        self.setFixedWidth(WINDOW_WIDTH)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(7)

        # 输入区
        self.label_input = QLineEdit()
        self.label_input.setPlaceholderText("任务名 (留空自动命名)")
        self.label_input.returnPressed.connect(self._start_first_preset)
        root.addWidget(self.label_input)

        # 预设按钮区
        self.preset_container = QVBoxLayout()
        self.preset_container.setSpacing(5)
        root.addLayout(self.preset_container)

        # 自定义 + 编辑预设
        tools = QHBoxLayout()
        tools.setSpacing(5)
        self.custom_min = QDoubleSpinBox()
        self.custom_min.setRange(0.1, 1440.0)
        self.custom_min.setDecimals(1)
        self.custom_min.setValue(5.0)
        self.custom_min.setSuffix(" min")
        add_btn = QPushButton("＋")
        add_btn.setFixedWidth(30)
        add_btn.setToolTip("按自定义分钟数开始")
        add_btn.clicked.connect(self._start_custom)
        edit_btn = QPushButton("编辑预设")
        edit_btn.clicked.connect(self._edit_presets)
        tools.addWidget(self.custom_min, 1)
        tools.addWidget(add_btn)
        tools.addWidget(edit_btn)
        root.addLayout(tools)

        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #e6e6eb;")
        root.addWidget(line)

        self.caption = QLabel("暂无进行中的倒计时")
        self.caption.setObjectName("caption")
        root.addWidget(self.caption)

        # 倒计时列表 (滚动)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setMaximumHeight(240)
        self.list_host = QWidget()
        self.list_layout = QVBoxLayout(self.list_host)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(4)
        self.list_layout.setAlignment(Qt.AlignTop)
        self.scroll.setWidget(self.list_host)
        root.addWidget(self.scroll)

        self._rebuild_presets()

        # 恢复已保存的倒计时
        for t in state["timers"]:
            self._add_timer_row(t)

        # 全局 tick
        self.ticker = QTimer(self)
        self.ticker.timeout.connect(self._tick)
        self.ticker.start(500)

    # -- 预设 --------------------------------------------------------------
    def _rebuild_presets(self):
        while self.preset_container.count():
            item = self.preset_container.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
        row = QHBoxLayout()
        row.setSpacing(5)
        count = 0
        for p in self.presets:
            btn = QPushButton(p["name"])
            btn.setObjectName("preset")
            btn.setToolTip(f"开始一个 {fmt_duration(p['seconds'])} 的倒计时")
            btn.clicked.connect(lambda _=False, sec=p["seconds"]: self._start_timer(sec))
            row.addWidget(btn)
            count += 1
            if count % 3 == 0:
                self.preset_container.addLayout(row)
                row = QHBoxLayout()
                row.setSpacing(5)
        if row.count():
            self.preset_container.addLayout(row)

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

    def _edit_presets(self):
        dlg = PresetEditor([dict(p) for p in self.presets], self)
        if dlg.exec() == QDialog.Accepted:
            new_presets = dlg.result_presets()
            if not new_presets:
                QMessageBox.warning(self, APP_NAME, "至少保留一个预设。")
                return
            self.presets = new_presets
            self._rebuild_presets()
            self._persist()

    # -- 启动倒计时 --------------------------------------------------------
    def _start_first_preset(self):
        if self.presets:
            self._start_timer(self.presets[0]["seconds"])

    def _start_custom(self):
        self._start_timer(int(round(self.custom_min.value() * 60)))

    def _start_timer(self, seconds: int):
        label = self.label_input.text().strip()
        if not label:
            label = datetime.now().strftime("任务-%H%M%S")
        timer = {
            "id": uuid.uuid4().hex,
            "label": label,
            "duration": seconds,
            "end_ts": time.time() + seconds,
        }
        self._add_timer_row(timer)
        self.label_input.clear()
        self.label_input.setFocus()
        self._persist()

    def _add_timer_row(self, timer: dict):
        row = TimerRow(timer, self._cancel_timer)
        timer["row"] = row
        self.timers.append(timer)
        self.list_layout.addWidget(row)
        row.update_remaining(timer["end_ts"] - time.time())
        self._update_caption()

    def _cancel_timer(self, timer: dict):
        self._remove_timer(timer)
        self._persist()

    def _remove_timer(self, timer: dict):
        row = timer.get("row")
        if row:
            row.setParent(None)
            row.deleteLater()
        if timer in self.timers:
            self.timers.remove(timer)
        self._update_caption()

    def _update_caption(self):
        n = len(self.timers)
        self.caption.setText("暂无进行中的倒计时" if n == 0 else f"进行中 · {n}")

    # -- tick --------------------------------------------------------------
    def _tick(self):
        now = time.time()
        finished = []
        for timer in self.timers:
            remaining = timer["end_ts"] - now
            row = timer.get("row")
            if row:
                row.update_remaining(remaining)
            if remaining <= 0:
                finished.append(timer)
        for timer in finished:
            send_notification(
                title=APP_NAME,
                subtitle=timer["label"],
                message="时间到, 去检查一下吧!",
            )
            self._remove_timer(timer)
        if finished:
            self._persist()

    def _persist(self):
        save_state(self.presets, self.timers)


def main():
    app = QApplication([])
    app.setApplicationName(APP_NAME)
    win = MultiTimer()
    win.show()
    # 放到桌面右下角
    area = app.primaryScreen().availableGeometry()
    frame = win.frameGeometry()
    win.move(area.right() - frame.width() - 20, area.bottom() - frame.height() - 20)
    win.raise_()
    win.activateWindow()
    app.exec()


if __name__ == "__main__":
    main()
