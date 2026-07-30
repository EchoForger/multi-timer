#!/usr/bin/env python3
"""MultiTimer - 多路倒计时小工具 (macOS 原生菜单栏应用)

使用 AppKit (PyObjC) 原生组件:
- 常驻菜单栏 NSStatusItem, 点击弹出 NSPopover (系统毛玻璃, 跟随深/浅色)
- 原生 NSTextField / NSButton / NSProgressIndicator
- 不在 Dock 显示 (ActivationPolicy = Accessory)
- 输入任务名 + 点预设时间即开始; 可并行多个倒计时
- 预设可增删改, 本地持久化; 必须先输入任务名才能开始计时
- 每行带进度条、＋1 分钟按钮; 任务名完整显示、放不下换行
- 到点发送静音 macOS 通知 (osascript); 结束后自动移除
"""

import json
import subprocess
import time
import uuid
from pathlib import Path

import objc
from Foundation import NSObject, NSTimer, NSMakeRect, NSMakeSize
from PyObjCTools import AppHelper
from AppKit import (
    NSApplication,
    NSApp,
    NSApplicationActivationPolicyAccessory,
    NSStatusBar,
    NSVariableStatusItemLength,
    NSImage,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSViewController,
    NSView,
    NSStackView,
    NSTextField,
    NSButton,
    NSBox,
    NSBoxSeparator,
    NSProgressIndicator,
    NSProgressIndicatorStyleBar,
    NSColor,
    NSFont,
    NSFontWeightSemibold,
    NSUserInterfaceLayoutOrientationVertical,
    NSUserInterfaceLayoutOrientationHorizontal,
    NSStackViewDistributionFillEqually,
    NSLayoutConstraintOrientationHorizontal,
    NSLineBreakByCharWrapping,
    NSMinYEdge,
    NSControlSizeSmall,
    NSBezelStyleRounded,
    NSImageNameStatusAvailable,
)

APP_NAME = "MultiTimer"
STATE_PATH = Path.home() / ".config" / "multitimer" / "state.json"
PANEL_WIDTH = 260
DEFAULT_PRESETS = [
    {"name": "1min", "seconds": 60},
    {"name": "5min", "seconds": 300},
    {"name": "10min", "seconds": 600},
    {"name": "15min", "seconds": 900},
    {"name": "30min", "seconds": 1800},
]


# ---------------------------------------------------------------------------
# 纯逻辑: 格式化 / 通知 / 持久化
# ---------------------------------------------------------------------------
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
    """osascript 发送 macOS 通知 (无 sound => 静音); argv 传参避免特殊字符问题。"""
    try:
        subprocess.Popen(
            ["osascript", "-e", _NOTIFY_SCRIPT, title, subtitle, message],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


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
# 让闭包可以作为 target/action
# ---------------------------------------------------------------------------
class _Action(NSObject):
    def initWithCallback_(self, cb):
        self = objc.super(_Action, self).init()
        if self is None:
            return None
        self._cb = cb
        return self

    def invoke_(self, sender):
        self._cb(sender)


# ---------------------------------------------------------------------------
# 一些原生控件的构造帮助函数
# ---------------------------------------------------------------------------
def _hstack(spacing=6):
    v = NSStackView.alloc().init()
    v.setOrientation_(NSUserInterfaceLayoutOrientationHorizontal)
    v.setSpacing_(spacing)
    return v


def _vstack(spacing=8):
    v = NSStackView.alloc().init()
    v.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
    v.setSpacing_(spacing)
    v.setAlignment_(1)  # NSLayoutAttributeLeading-ish; leading align
    return v


def _section_label(text):
    lbl = NSTextField.labelWithString_(text)
    lbl.setFont_(NSFont.systemFontOfSize_weight_(11, NSFontWeightSemibold))
    lbl.setTextColor_(NSColor.secondaryLabelColor())
    return lbl


def _button(title, cb, retain, accent=False, small=False):
    action = _Action.alloc().initWithCallback_(cb)
    retain.append(action)
    btn = NSButton.buttonWithTitle_target_action_(title, action, "invoke:")
    btn.setBezelStyle_(NSBezelStyleRounded)
    if small:
        btn.setControlSize_(NSControlSizeSmall)
        btn.setFont_(NSFont.systemFontOfSize_(11))
    if accent:
        btn.setBezelColor_(NSColor.controlAccentColor())
    return btn


# ---------------------------------------------------------------------------
# 主控制器 (菜单栏 + 弹出面板)
# ---------------------------------------------------------------------------
class MultiTimerApp(NSObject):
    def init(self):
        self = objc.super(MultiTimerApp, self).init()
        if self is None:
            return None
        state = load_state()
        self.presets = state["presets"]
        self.timers = []          # dict: id/label/end_ts/duration/view/name/progress/actions
        self._retain = []         # 全局 target 保活
        self._closed_at = 0.0
        self._build_status_item()
        self._build_popover()
        for t in state["timers"]:
            self._add_timer_row(t)
        self._update_size()
        self._start_ticker()
        return self

    # -- 菜单栏图标 --------------------------------------------------------
    def _build_status_item(self):
        bar = NSStatusBar.systemStatusBar()
        self.status_item = bar.statusItemWithLength_(NSVariableStatusItemLength)
        btn = self.status_item.button()
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("timer", APP_NAME)
        if img is None:
            img = NSImage.imageNamed_(NSImageNameStatusAvailable)
        if img is not None:
            img.setTemplate_(True)
            btn.setImage_(img)
        else:
            btn.setTitle_("⏱")
        toggle = _Action.alloc().initWithCallback_(lambda s: self._toggle_popover())
        self._retain.append(toggle)
        btn.setTarget_(toggle)
        btn.setAction_("invoke:")

    # -- 弹出面板 ----------------------------------------------------------
    def _build_popover(self):
        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, PANEL_WIDTH + 28, 200))
        self.content_view = content

        root = _vstack(9)
        root.setTranslatesAutoresizingMaskIntoConstraints_(False)
        content.addSubview_(root)
        self.root_stack = root
        root.leadingAnchor().constraintEqualToAnchor_constant_(content.leadingAnchor(), 14).setActive_(True)
        root.trailingAnchor().constraintEqualToAnchor_constant_(content.trailingAnchor(), -14).setActive_(True)
        root.topAnchor().constraintEqualToAnchor_constant_(content.topAnchor(), 12).setActive_(True)
        root.bottomAnchor().constraintEqualToAnchor_constant_(content.bottomAnchor(), -14).setActive_(True)
        root.widthAnchor().constraintEqualToConstant_(PANEL_WIDTH).setActive_(True)

        # 头部
        header = _hstack(6)
        header.setDistribution_(0)
        title = NSTextField.labelWithString_(APP_NAME)
        title.setFont_(NSFont.systemFontOfSize_weight_(13, NSFontWeightSemibold))
        quit_btn = _button("退出", lambda s: self._quit(), self._retain, small=True)
        header.addArrangedSubview_(title)
        spacer = NSView.alloc().init()
        header.addArrangedSubview_(spacer)
        spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        header.addArrangedSubview_(quit_btn)
        root.addArrangedSubview_(header)
        self._fill_width(header)

        # 输入框
        self.input_field = NSTextField.textFieldWithString_("")
        self.input_field.setPlaceholderString_("先输入任务名, 再点时间开始")
        root.addArrangedSubview_(self.input_field)
        self._fill_width(self.input_field)

        # 预设按钮区
        self.presets_stack = _vstack(6)
        root.addArrangedSubview_(self.presets_stack)
        self._fill_width(self.presets_stack)
        self._rebuild_presets()

        # 自定义分钟 + 编辑预设
        tools = _hstack(6)
        self.custom_field = NSTextField.textFieldWithString_("5")
        self.custom_field.setAlignment_(1)
        cf_w = self.custom_field.widthAnchor().constraintEqualToConstant_(46)
        cf_w.setActive_(True)
        min_lbl = NSTextField.labelWithString_("min")
        min_lbl.setTextColor_(NSColor.secondaryLabelColor())
        add_btn = _button("＋ 开始", lambda s: self._start_custom(), self._retain, small=True)
        edit_btn = _button("编辑预设", lambda s: self._edit_presets(), self._retain, small=True)
        tools.addArrangedSubview_(self.custom_field)
        tools.addArrangedSubview_(min_lbl)
        tools.addArrangedSubview_(add_btn)
        tools.addArrangedSubview_(edit_btn)
        root.addArrangedSubview_(tools)
        self._fill_width(tools)

        # 分隔线
        sep = NSBox.alloc().init()
        sep.setBoxType_(NSBoxSeparator)
        root.addArrangedSubview_(sep)
        self._fill_width(sep)

        # 进行中标题 + 列表
        self.section_label = _section_label("暂无进行中的倒计时")
        root.addArrangedSubview_(self.section_label)
        self.timers_stack = _vstack(6)
        root.addArrangedSubview_(self.timers_stack)
        self._fill_width(self.timers_stack)

        vc = NSViewController.alloc().init()
        vc.setView_(content)
        self._vc = vc
        self.popover = NSPopover.alloc().init()
        self.popover.setContentViewController_(vc)
        self.popover.setBehavior_(NSPopoverBehaviorTransient)
        self.popover.setAnimates_(True)
        self.popover.setDelegate_(self)

    def _fill_width(self, view):
        view.leadingAnchor().constraintEqualToAnchor_(self.root_stack.leadingAnchor()).setActive_(True)
        view.trailingAnchor().constraintEqualToAnchor_(self.root_stack.trailingAnchor()).setActive_(True)

    # -- 预设 --------------------------------------------------------------
    def _rebuild_presets(self):
        for sub in list(self.presets_stack.arrangedSubviews()):
            self.presets_stack.removeArrangedSubview_(sub)
            sub.removeFromSuperview()
        row = None
        for i, p in enumerate(self.presets):
            if i % 3 == 0:
                row = _hstack(6)
                row.setDistribution_(NSStackViewDistributionFillEqually)
                self.presets_stack.addArrangedSubview_(row)
                self._fill_width(row)
            btn = _button(p["name"], self._make_start_cb(p["seconds"]), self._retain, accent=True)
            row.addArrangedSubview_(btn)

    def _make_start_cb(self, seconds):
        return lambda s: self._start_timer(seconds)

    def _edit_presets(self):
        # 用简易 osascript 对话依次询问过于繁琐; 这里用一个多行输入弹窗。
        from AppKit import NSAlert, NSTextView, NSScrollView, NSMakeRect as _R
        lines = "\n".join(f"{p['name']}={p['seconds'] // 60}" for p in self.presets)
        alert = NSAlert.alloc().init()
        alert.setMessageText_("编辑预设")
        alert.setInformativeText_("每行一个: 名称=分钟 (例如 5min=5)")
        alert.addButtonWithTitle_("保存")
        alert.addButtonWithTitle_("取消")
        tv = NSTextView.alloc().initWithFrame_(_R(0, 0, 240, 120))
        tv.setString_(lines)
        scroll = NSScrollView.alloc().initWithFrame_(_R(0, 0, 240, 120))
        scroll.setDocumentView_(tv)
        scroll.setHasVerticalScroller_(True)
        alert.setAccessoryView_(scroll)
        if alert.runModal() != 1000:  # 非"保存"
            return
        new = []
        for raw in tv.string().splitlines():
            raw = raw.strip()
            if not raw or "=" not in raw:
                continue
            name, _, mins = raw.partition("=")
            name = name.strip()
            try:
                seconds = int(round(float(mins.strip()) * 60))
            except ValueError:
                continue
            if name and seconds > 0:
                new.append({"name": name, "seconds": seconds})
        if new:
            self.presets = new
            self._rebuild_presets()
            self._persist()
            self._update_size()

    # -- 启动倒计时 --------------------------------------------------------
    def _start_custom(self):
        try:
            minutes = float(self.custom_field.stringValue().strip())
        except ValueError:
            return
        if minutes > 0:
            self._start_timer(int(round(minutes * 60)))

    def _start_timer(self, seconds):
        label = self.input_field.stringValue().strip()
        if not label:
            # 没有任务名不开始计时: 提示先填写任务名
            self.input_field.setPlaceholderString_("⚠️ 请先输入任务名")
            win = self.input_field.window()
            if win is not None:
                win.makeFirstResponder_(self.input_field)
            return
        timer = {
            "id": uuid.uuid4().hex,
            "label": label,
            "duration": int(seconds),
            "end_ts": time.time() + seconds,
        }
        self._add_timer_row(timer)
        self.input_field.setStringValue_("")
        self.input_field.setPlaceholderString_("先输入任务名, 再点时间开始")
        self._persist()
        self._update_size()

    def _add_timer_row(self, timer):
        actions = []
        rowv = _vstack(4)

        name = NSTextField.wrappingLabelWithString_(timer["label"])
        name.setPreferredMaxLayoutWidth_(PANEL_WIDTH - 4)
        name.cell().setLineBreakMode_(NSLineBreakByCharWrapping)
        rowv.addArrangedSubview_(name)

        bottom = _hstack(6)
        progress = NSProgressIndicator.alloc().init()
        progress.setStyle_(NSProgressIndicatorStyleBar)
        progress.setIndeterminate_(False)
        progress.setControlSize_(NSControlSizeSmall)
        progress.setMinValue_(0.0)
        progress.setMaxValue_(1000.0)
        progress.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)

        remaining = NSTextField.labelWithString_("--:--")
        remaining.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(12, 0))
        remaining.setContentHuggingPriority_forOrientation_(750, NSLayoutConstraintOrientationHorizontal)

        plus = _button("＋1", self._make_extend_cb(timer), actions, small=True)
        cancel = _button("✕", self._make_cancel_cb(timer), actions, small=True)

        bottom.addArrangedSubview_(progress)
        bottom.addArrangedSubview_(remaining)
        bottom.addArrangedSubview_(plus)
        bottom.addArrangedSubview_(cancel)
        rowv.addArrangedSubview_(bottom)

        self.timers_stack.addArrangedSubview_(rowv)
        self._fill_width(rowv)
        bottom.leadingAnchor().constraintEqualToAnchor_(rowv.leadingAnchor()).setActive_(True)
        bottom.trailingAnchor().constraintEqualToAnchor_(rowv.trailingAnchor()).setActive_(True)
        name.leadingAnchor().constraintEqualToAnchor_(rowv.leadingAnchor()).setActive_(True)
        name.trailingAnchor().constraintEqualToAnchor_(rowv.trailingAnchor()).setActive_(True)

        timer["view"] = rowv
        timer["progress"] = progress
        timer["remaining"] = remaining
        timer["actions"] = actions
        self.timers.append(timer)
        self._retain.extend(actions)
        self._update_row(timer)
        self._update_section()

    def _make_extend_cb(self, timer):
        return lambda s: self._extend_timer(timer, 60)

    def _make_cancel_cb(self, timer):
        return lambda s: self._cancel_timer(timer)

    def _extend_timer(self, timer, seconds):
        timer["end_ts"] += seconds
        timer["duration"] += seconds
        self._update_row(timer)
        self._persist()

    def _cancel_timer(self, timer):
        self._remove_timer(timer)
        self._persist()
        self._update_size()

    def _remove_timer(self, timer):
        view = timer.get("view")
        if view is not None:
            self.timers_stack.removeArrangedSubview_(view)
            view.removeFromSuperview()
        for a in timer.get("actions", []):
            if a in self._retain:
                self._retain.remove(a)
        if timer in self.timers:
            self.timers.remove(timer)
        self._update_section()

    def _update_row(self, timer):
        remaining = timer["end_ts"] - time.time()
        timer["remaining"].setStringValue_(fmt_remaining(remaining))
        frac = max(0.0, min(1.0, remaining / max(1, timer["duration"])))
        timer["progress"].setDoubleValue_(frac * 1000.0)
        color = NSColor.systemRedColor() if remaining <= 10 else NSColor.labelColor()
        timer["remaining"].setTextColor_(color)

    def _update_section(self):
        n = len(self.timers)
        self.section_label.setStringValue_(
            "暂无进行中的倒计时" if n == 0 else f"进行中 · {n}"
        )

    # -- 计时循环 ----------------------------------------------------------
    def _start_ticker(self):
        self._ticker = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, "tick:", None, True
        )

    def tick_(self, _timer):
        finished = []
        for timer in self.timers:
            self._update_row(timer)
            if timer["end_ts"] - time.time() <= 0:
                finished.append(timer)
        for timer in finished:
            send_notification(APP_NAME, timer["label"], "时间到, 去检查一下吧!")
            self._remove_timer(timer)
        if finished:
            self._persist()
            self._update_size()

    # -- 弹出/收起 ---------------------------------------------------------
    def _toggle_popover(self):
        if self.popover.isShown():
            self.popover.close()
            return
        if time.time() - self._closed_at < 0.25:
            return
        btn = self.status_item.button()
        self.popover.showRelativeToRect_ofView_preferredEdge_(btn.bounds(), btn, NSMinYEdge)
        NSApp.activateIgnoringOtherApps_(True)
        self.input_field.window().makeFirstResponder_(self.input_field)

    def popoverDidClose_(self, _notification):
        self._closed_at = time.time()

    def _update_size(self):
        self.content_view.layoutSubtreeIfNeeded()
        self.popover.setContentSize_(self.content_view.fittingSize())

    def _persist(self):
        save_state(self.presets, self.timers)

    def _quit(self):
        self._persist()
        NSApp.terminate_(None)


def main():
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)  # 不显示 Dock 图标
    delegate = MultiTimerApp.alloc().init()
    app.setDelegate_(delegate)
    global _APP_DELEGATE
    _APP_DELEGATE = delegate  # 保活
    AppHelper.runEventLoop(installInterrupt=True)


if __name__ == "__main__":
    main()
