#!/usr/bin/env python3
"""MultiTimer - 多路倒计时小工具 (macOS 原生菜单栏应用)

使用 AppKit (PyObjC) 原生组件:
- 常驻菜单栏 NSStatusItem, 点击弹出 NSPopover (系统毛玻璃, 跟随深/浅色)
- 原生 NSTextField / NSButton，以及跟随系统强调色的轻量进度条
- 不在 Dock 显示 (ActivationPolicy = Accessory)
- 输入任务名 + 点预设时间即开始; 可并行多个倒计时
- 预设可增删改, 本地持久化; 未填任务名时自动使用 "任务 N"
- 每行带进度条和延时按钮; 任务名单行省略、可原生行内改名
- 到点由 MultiTimer.app 通过 UNUserNotificationCenter 发出可交互通知
  (点击 "已检查" 按钮 => 直接从列表中移除对应倒计时)
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

import objc
from Foundation import NSObject, NSTimer, NSMakeRect, NSMakeSize, NSNotificationCenter
from PyObjCTools import AppHelper
from UserNotifications import (
    UNUserNotificationCenter,
    UNMutableNotificationContent,
    UNNotificationRequest,
    UNNotificationAction,
    UNNotificationCategory,
    UNAuthorizationOptionAlert,
    UNAuthorizationOptionSound,
    UNNotificationActionOptionNone,
    UNNotificationCategoryOptionNone,
    UNNotificationPresentationOptionBanner,
    UNNotificationPresentationOptionList,
    UNNotificationPresentationOptionSound,
)
from AppKit import (
    NSApplication,
    NSApp,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSStatusBar,
    NSSquareStatusItemLength,
    NSMenu,
    NSMenuItem,
    NSImage,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSPopoverBehaviorApplicationDefined,
    NSViewController,
    NSView,
    NSImageView,
    NSImageScaleProportionallyUpOrDown,
    NSStackView,
    NSTextField,
    NSButton,
    NSBox,
    NSBoxSeparator,
    NSColor,
    NSFont,
    NSFontWeightBold,
    NSFontWeightMedium,
    NSFontWeightSemibold,
    NSUserInterfaceLayoutOrientationVertical,
    NSUserInterfaceLayoutOrientationHorizontal,
    NSStackViewDistributionFillEqually,
    NSLayoutConstraintOrientationHorizontal,
    NSLineBreakByTruncatingMiddle,
    NSMinYEdge,
    NSControlSizeSmall,
    NSBezelStyleRounded,
    NSFocusRingTypeDefault,
    NSFocusRingTypeNone,
    NSPressureConfiguration,
    NSPressureBehaviorPrimaryDeepClick,
    NSImageNameStatusAvailable,
    NSAppearanceNameAqua,
    NSAppearanceNameDarkAqua,
    NSAppearance,
    NSWindow,
    NSWindowStyleMaskTitled,
    NSWindowStyleMaskClosable,
    NSBackingStoreBuffered,
    NSBitmapImageFileTypePNG,
    NSSystemColorsDidChangeNotification,
)

APP_NAME = "MultiTimer"
APP_VERSION = "0.3.1"
STATE_PATH = Path(
    os.environ.get(
        "MULTITIMER_STATE_PATH",
        str(Path.home() / ".config" / "multitimer" / "state.json"),
    )
)
PANEL_WIDTH = 296
DEFAULT_PRESETS = [
    {"name": "1min", "seconds": 60},
    {"name": "5min", "seconds": 300},
    {"name": "10min", "seconds": 600},
    {"name": "15min", "seconds": 900},
    {"name": "30min", "seconds": 1800},
]


def resource_path(relative: str) -> Path:
    """Return an asset path in source runs and PyInstaller bundles."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / relative


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


_NOTIF_CATEGORY = "TIMER_DONE"
_NOTIF_ACTION_CHECK = "MARK_CHECKED"


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


class _RenameTextField(NSTextField):
    """Single-line label that starts native inline editing on macOS gestures."""

    def initWithFrame_(self, frame):
        self = objc.super(_RenameTextField, self).initWithFrame_(frame)
        if self is None:
            return None
        self._rename_controller = None
        self._deep_press_engaged = False
        config = NSPressureConfiguration.alloc().initWithPressureBehavior_(
            NSPressureBehaviorPrimaryDeepClick
        )
        self.setPressureConfiguration_(config)
        self._pressure_configuration = config
        return self

    def setRenameController_(self, controller):
        self._rename_controller = controller

    def mouseDown_(self, event):
        if event.clickCount() >= 2 and self._rename_controller is not None:
            self._rename_controller.begin()
            return
        objc.super(_RenameTextField, self).mouseDown_(event)

    def _handle_pressure_stage(self, stage):
        if stage >= 2:
            if not self._deep_press_engaged:
                self._deep_press_engaged = True
                if self._rename_controller is not None:
                    self._rename_controller.begin()
            return True
        self._deep_press_engaged = False
        return False

    def pressureChangeWithEvent_(self, event):
        if self._handle_pressure_stage(event.stage()):
            return
        objc.super(_RenameTextField, self).pressureChangeWithEvent_(event)


class _RenameController(NSObject):
    """Own the lifecycle of one timer's inline NSTextField editor."""

    def initWithOwner_timer_field_(self, owner, timer, field):
        self = objc.super(_RenameController, self).init()
        if self is None:
            return None
        self._owner = owner
        self._timer = timer
        self._field = field
        self._editing = False
        self._cancel_requested = False
        self._original = timer["label"]
        return self

    def begin(self):
        if self._editing:
            return
        self._editing = True
        self._cancel_requested = False
        self._original = self._timer["label"]
        self._field.setEditable_(True)
        self._field.setSelectable_(True)
        self._field.setBezeled_(True)
        self._field.setDrawsBackground_(True)
        self._field.setFocusRingType_(NSFocusRingTypeDefault)
        window = self._field.window()
        if window is not None:
            window.makeFirstResponder_(self._field)
        self._field.selectText_(None)

    def _finish(self):
        if not self._editing:
            return
        value = self._original if self._cancel_requested else self._field.stringValue().strip()
        if not value:
            value = self._original
        self._timer["label"] = value
        self._field.setStringValue_(value)
        self._field.setToolTip_(f"{value}\n双击或用力按压以重命名")
        self._field.setEditable_(False)
        self._field.setSelectable_(False)
        self._field.setBezeled_(False)
        self._field.setDrawsBackground_(False)
        self._field.setFocusRingType_(NSFocusRingTypeNone)
        self._editing = False
        self._cancel_requested = False
        self._owner._persist()

    def controlTextDidEndEditing_(self, _notification):
        self._finish()

    def control_textView_doCommandBySelector_(self, control, _text_view, command):
        command_name = command.decode("ascii") if isinstance(command, bytes) else str(command)
        if command_name == "cancelOperation:":
            self._cancel_requested = True
            control.window().makeFirstResponder_(None)
            return True
        if command_name in {"insertNewline:", "insertLineBreak:"}:
            control.window().makeFirstResponder_(None)
            return True
        return False


class _CardView(NSView):
    """Rounded surface that follows the current macOS appearance."""

    def init(self):
        self = objc.super(_CardView, self).init()
        if self is None:
            return None
        self.setWantsLayer_(True)
        self.layer().setCornerRadius_(8.0)
        self.layer().setMasksToBounds_(True)
        self._apply_palette()
        return self

    def viewDidChangeEffectiveAppearance(self):
        objc.super(_CardView, self).viewDidChangeEffectiveAppearance()
        self._apply_palette()

    def _apply_palette(self):
        appearance = self.effectiveAppearance() or NSApp.effectiveAppearance()
        if appearance is None:
            return
        match = appearance.bestMatchFromAppearancesWithNames_(
            [NSAppearanceNameAqua, NSAppearanceNameDarkAqua]
        )
        color = NSColor.controlBackgroundColor()
        if match == NSAppearanceNameDarkAqua:
            color = color.colorWithAlphaComponent_(0.72)
        else:
            color = color.colorWithAlphaComponent_(0.82)
        self.layer().setBackgroundColor_(color.CGColor())


class _ProgressView(NSView):
    """Compact progress bar that follows the macOS system accent color."""

    def init(self):
        self = objc.super(_ProgressView, self).init()
        if self is None:
            return None
        self._value = 0.0
        self.setWantsLayer_(True)
        self.layer().setCornerRadius_(2.0)
        self.layer().setMasksToBounds_(True)
        self._fill = NSView.alloc().init()
        self._fill.setWantsLayer_(True)
        self._fill.layer().setCornerRadius_(2.0)
        self.addSubview_(self._fill)
        self.refreshAccent()
        return self

    def intrinsicContentSize(self):
        return NSMakeSize(-1.0, 4.0)

    def setDoubleValue_(self, value):
        self._value = max(0.0, min(1000.0, float(value)))
        self.setNeedsLayout_(True)

    def layout(self):
        objc.super(_ProgressView, self).layout()
        bounds = self.bounds()
        width = bounds.size.width * (self._value / 1000.0)
        self._fill.setFrame_(NSMakeRect(0, 0, width, bounds.size.height))

    def viewDidChangeEffectiveAppearance(self):
        objc.super(_ProgressView, self).viewDidChangeEffectiveAppearance()
        self.refreshAccent()

    def refreshAccent(self):
        track = NSColor.separatorColor().colorWithAlphaComponent_(0.55)
        self.layer().setBackgroundColor_(track.CGColor())
        self._fill.layer().setBackgroundColor_(NSColor.controlAccentColor().CGColor())


# ---------------------------------------------------------------------------
# 一些原生控件的构造帮助函数
# ---------------------------------------------------------------------------
def _hstack(spacing=6):
    v = NSStackView.alloc().init()
    v.setOrientation_(NSUserInterfaceLayoutOrientationHorizontal)
    v.setSpacing_(spacing)
    return v


def _vstack(spacing=6):
    v = NSStackView.alloc().init()
    v.setOrientation_(NSUserInterfaceLayoutOrientationVertical)
    v.setSpacing_(spacing)
    v.setAlignment_(1)  # NSLayoutAttributeLeading-ish; leading align
    return v


def _section_label(text):
    lbl = NSTextField.labelWithString_(text)
    lbl.setFont_(NSFont.systemFontOfSize_weight_(10, NSFontWeightSemibold))
    lbl.setTextColor_(NSColor.secondaryLabelColor())
    return lbl


def _button(title, cb, retain, accent=False, small=False, quiet=False):
    action = _Action.alloc().initWithCallback_(cb)
    retain.append(action)
    btn = NSButton.buttonWithTitle_target_action_(title, action, "invoke:")
    btn.setBezelStyle_(NSBezelStyleRounded)
    if small:
        btn.setControlSize_(NSControlSizeSmall)
        btn.setFont_(NSFont.systemFontOfSize_weight_(11, NSFontWeightMedium))
    if accent:
        btn.setBezelColor_(NSColor.controlAccentColor())
    return btn


def _embed_with_insets(container, child, top=10, right=10, bottom=10, left=10):
    child.setTranslatesAutoresizingMaskIntoConstraints_(False)
    container.addSubview_(child)
    child.topAnchor().constraintEqualToAnchor_constant_(container.topAnchor(), top).setActive_(True)
    child.trailingAnchor().constraintEqualToAnchor_constant_(container.trailingAnchor(), -right).setActive_(True)
    child.bottomAnchor().constraintEqualToAnchor_constant_(container.bottomAnchor(), -bottom).setActive_(True)
    child.leadingAnchor().constraintEqualToAnchor_constant_(container.leadingAnchor(), left).setActive_(True)


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
        self._initial_timers = state["timers"]
        self.timers = []          # dict: id/label/end_ts/duration/view/name/progress/actions
        self._retain = []         # 全局 target 保活
        self._closed_at = 0.0
        self._did_finish_launching = False
        return self

    def applicationDidFinishLaunching_(self, _notification):
        """Create the status item only after AppKit has finished launching."""
        if self._did_finish_launching:
            return
        self._did_finish_launching = True
        self._setup_notifications()
        self._build_main_menu()
        self._build_status_item()
        self._build_popover()
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "systemColorsDidChange:", NSSystemColorsDidChangeNotification, None
        )
        for t in self._initial_timers:
            self._add_timer_row(t)
        self._initial_timers = []
        self._update_size()
        self._start_ticker()
        if os.environ.get("MULTITIMER_PREVIEW") == "1":
            self._show_preview_window()

    # -- 主菜单 (让 ⌘C/⌘V/⌘X/⌘A 能路由到输入框) -------------------------
    def _build_main_menu(self):
        main = NSMenu.alloc().init()
        edit_item = NSMenuItem.alloc().init()
        main.addItem_(edit_item)
        edit_menu = NSMenu.alloc().initWithTitle_("Edit")
        edit_item.setSubmenu_(edit_menu)

        def add(title, selector, key):
            it = NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, selector, key)
            edit_menu.addItem_(it)

        add("Undo", "undo:", "z")
        add("Redo", "redo:", "Z")
        edit_menu.addItem_(NSMenuItem.separatorItem())
        add("Cut", "cut:", "x")
        add("Copy", "copy:", "c")
        add("Paste", "paste:", "v")
        add("Select All", "selectAll:", "a")
        NSApp.setMainMenu_(main)

    # -- 菜单栏图标 --------------------------------------------------------
    def _build_status_item(self):
        bar = NSStatusBar.systemStatusBar()
        self.status_item = bar.statusItemWithLength_(NSSquareStatusItemLength)
        # Do not set an autosave name here. On recent macOS versions, launching
        # an installed build and a development build with the same bundle ID can
        # make Control Center classify the duplicate autosaved item as blocked,
        # leaving the application alive without a visible menu-bar icon.
        btn = self.status_item.button()
        btn.setToolTip_(APP_NAME)
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
        if self.status_item.respondsToSelector_("setVisible:"):
            self.status_item.setVisible_(True)

    # -- 弹出面板 ----------------------------------------------------------
    def _build_popover(self):
        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, PANEL_WIDTH + 20, 220))
        self.content_view = content

        root = _vstack(5)
        root.setTranslatesAutoresizingMaskIntoConstraints_(False)
        content.addSubview_(root)
        self.root_stack = root
        root.leadingAnchor().constraintEqualToAnchor_constant_(content.leadingAnchor(), 10).setActive_(True)
        root.trailingAnchor().constraintEqualToAnchor_constant_(content.trailingAnchor(), -10).setActive_(True)
        root.topAnchor().constraintEqualToAnchor_constant_(content.topAnchor(), 9).setActive_(True)
        root.bottomAnchor().constraintEqualToAnchor_constant_(content.bottomAnchor(), -9).setActive_(True)
        root.widthAnchor().constraintEqualToConstant_(PANEL_WIDTH).setActive_(True)

        # 品牌头部
        header = _hstack(7)
        header.setDistribution_(0)
        icon = NSImage.alloc().initWithContentsOfFile_(str(resource_path("assets/app-icon.png")))
        if icon is not None:
            icon_view = NSImageView.imageViewWithImage_(icon)
            icon_view.setImageScaling_(NSImageScaleProportionallyUpOrDown)
            icon_view.widthAnchor().constraintEqualToConstant_(26).setActive_(True)
            icon_view.heightAnchor().constraintEqualToConstant_(26).setActive_(True)
            header.addArrangedSubview_(icon_view)

        title = NSTextField.labelWithString_(APP_NAME)
        title.setFont_(NSFont.systemFontOfSize_weight_(13.5, NSFontWeightSemibold))
        header.addArrangedSubview_(title)
        spacer = NSView.alloc().init()
        header.addArrangedSubview_(spacer)
        spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        quit_btn = _button("×", lambda s: self._quit(), self._retain, small=True, quiet=True)
        quit_btn.setToolTip_("退出 MultiTimer")
        header.addArrangedSubview_(quit_btn)
        root.addArrangedSubview_(header)
        self._fill_width(header)

        # 新建计时器
        self.input_field = NSTextField.textFieldWithString_("")
        self.input_field.setPlaceholderString_("计时名称（可选）")
        self.input_field.setFont_(NSFont.systemFontOfSize_(12))
        self.input_field.heightAnchor().constraintEqualToConstant_(25).setActive_(True)
        root.addArrangedSubview_(self.input_field)
        self._fill_width(self.input_field)

        # 快速开始
        presets_header = _hstack(6)
        presets_header.addArrangedSubview_(_section_label("快速开始"))
        preset_spacer = NSView.alloc().init()
        presets_header.addArrangedSubview_(preset_spacer)
        preset_spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        edit_btn = _button("编辑", lambda s: self._edit_presets(), self._retain, small=True, quiet=True)
        presets_header.addArrangedSubview_(edit_btn)
        root.addArrangedSubview_(presets_header)
        self._fill_width(presets_header)

        self.presets_stack = _vstack(4)
        root.addArrangedSubview_(self.presets_stack)
        self._fill_width(self.presets_stack)
        self._rebuild_presets()

        # 自定义时长卡片
        custom_card = _CardView.alloc().init()
        tools = _hstack(5)
        custom_label = NSTextField.labelWithString_("自定义")
        custom_label.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightMedium))
        tools.addArrangedSubview_(custom_label)
        tools_spacer = NSView.alloc().init()
        tools.addArrangedSubview_(tools_spacer)
        tools_spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        self.custom_field = NSTextField.textFieldWithString_("5")
        self.custom_field.setAlignment_(1)
        cf_w = self.custom_field.widthAnchor().constraintEqualToConstant_(44)
        cf_w.setActive_(True)
        min_lbl = NSTextField.labelWithString_("分钟")
        min_lbl.setTextColor_(NSColor.secondaryLabelColor())
        add_btn = _button("开始", lambda s: self._start_custom(), self._retain, accent=True, small=True)
        tools.addArrangedSubview_(self.custom_field)
        tools.addArrangedSubview_(min_lbl)
        tools.addArrangedSubview_(add_btn)
        self.custom_field.heightAnchor().constraintEqualToConstant_(22).setActive_(True)
        _embed_with_insets(custom_card, tools, top=5, right=7, bottom=5, left=9)
        root.addArrangedSubview_(custom_card)
        self._fill_width(custom_card)

        # 进行中标题 + 列表
        self.section_label = _section_label("暂无进行中的计时器")
        root.addArrangedSubview_(self.section_label)
        self.timers_stack = _vstack(5)
        root.addArrangedSubview_(self.timers_stack)
        self._fill_width(self.timers_stack)

        vc = NSViewController.alloc().init()
        vc.setView_(content)
        self._vc = vc
        self.popover = NSPopover.alloc().init()
        self.popover.setContentViewController_(vc)
        behavior = (
            NSPopoverBehaviorApplicationDefined
            if os.environ.get("MULTITIMER_PREVIEW") == "1"
            else NSPopoverBehaviorTransient
        )
        self.popover.setBehavior_(behavior)
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
                row = _hstack(5)
                row.setDistribution_(NSStackViewDistributionFillEqually)
                self.presets_stack.addArrangedSubview_(row)
                self._fill_width(row)
            btn = _button(p["name"], self._make_start_cb(p["seconds"]), self._retain, small=True)
            btn.heightAnchor().constraintEqualToConstant_(23).setActive_(True)
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
            label = self._default_label()
        timer = {
            "id": uuid.uuid4().hex,
            "label": label,
            "duration": int(seconds),
            "end_ts": time.time() + seconds,
        }
        self._add_timer_row(timer)
        self.input_field.setStringValue_("")
        self.input_field.setPlaceholderString_("计时名称（可选）")
        self._persist()
        self._update_size()

    def _default_label(self):
        used = {t.get("label") for t in self.timers}
        i = 1
        while True:
            candidate = f"任务 {i}"
            if candidate not in used:
                return candidate
            i += 1

    def _add_timer_row(self, timer):
        actions = []
        card = _CardView.alloc().init()
        rowv = _vstack(4)

        name = _RenameTextField.alloc().initWithFrame_(NSMakeRect(0, 0, 100, 20))
        name.setStringValue_(timer["label"])
        name.setFont_(NSFont.systemFontOfSize_weight_(12, NSFontWeightMedium))
        name.setEditable_(False)
        name.setSelectable_(False)
        name.setBezeled_(False)
        name.setBordered_(False)
        name.setDrawsBackground_(False)
        name.setFocusRingType_(NSFocusRingTypeNone)
        name.setLineBreakMode_(NSLineBreakByTruncatingMiddle)
        name.setMaximumNumberOfLines_(1)
        name.setToolTip_(f"{timer['label']}\n双击或用力按压以重命名")
        name.setContentHuggingPriority_forOrientation_(249, NSLayoutConstraintOrientationHorizontal)
        name.setContentCompressionResistancePriority_forOrientation_(249, NSLayoutConstraintOrientationHorizontal)
        rename = _RenameController.alloc().initWithOwner_timer_field_(self, timer, name)
        name.setRenameController_(rename)
        name.setDelegate_(rename)
        actions.append(rename)

        top = _hstack(5)
        top.addArrangedSubview_(name)
        title_spacer = NSView.alloc().init()
        top.addArrangedSubview_(title_spacer)
        title_spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)

        remaining = NSTextField.labelWithString_("--:--")
        remaining.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(13, NSFontWeightSemibold))
        remaining.setTextColor_(NSColor.controlAccentColor())
        remaining.setContentHuggingPriority_forOrientation_(750, NSLayoutConstraintOrientationHorizontal)
        top.addArrangedSubview_(remaining)
        rowv.addArrangedSubview_(top)

        progress = _ProgressView.alloc().init()
        progress.heightAnchor().constraintEqualToConstant_(3).setActive_(True)
        rowv.addArrangedSubview_(progress)

        bottom = _hstack(4)
        plus1 = _button("＋1分", self._make_extend_cb(timer, 60), actions, small=True, quiet=True)
        plus10 = _button("＋10分", self._make_extend_cb(timer, 600), actions, small=True, quiet=True)
        plus60 = _button("＋1时", self._make_extend_cb(timer, 3600), actions, small=True, quiet=True)
        cancel = _button("×", self._make_cancel_cb(timer), actions, small=True, quiet=True)
        restart = _button("重新计时", self._make_restart_cb(timer), actions, small=True, quiet=True)
        done = _button("✓ 已检查", self._make_cancel_cb(timer), actions, small=True, accent=True)
        restart.setHidden_(True)
        done.setHidden_(True)
        for button in (plus1, plus10, plus60, cancel, restart, done):
            button.heightAnchor().constraintEqualToConstant_(22).setActive_(True)

        bottom.addArrangedSubview_(plus1)
        bottom.addArrangedSubview_(plus10)
        bottom.addArrangedSubview_(plus60)
        action_spacer = NSView.alloc().init()
        bottom.addArrangedSubview_(action_spacer)
        action_spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        bottom.addArrangedSubview_(cancel)
        bottom.addArrangedSubview_(restart)
        bottom.addArrangedSubview_(done)
        rowv.addArrangedSubview_(bottom)

        _embed_with_insets(card, rowv, top=6, right=8, bottom=6, left=8)
        self.timers_stack.addArrangedSubview_(card)
        self._fill_width(card)
        top.leadingAnchor().constraintEqualToAnchor_(rowv.leadingAnchor()).setActive_(True)
        top.trailingAnchor().constraintEqualToAnchor_(rowv.trailingAnchor()).setActive_(True)
        progress.leadingAnchor().constraintEqualToAnchor_(rowv.leadingAnchor()).setActive_(True)
        progress.trailingAnchor().constraintEqualToAnchor_(rowv.trailingAnchor()).setActive_(True)
        bottom.leadingAnchor().constraintEqualToAnchor_(rowv.leadingAnchor()).setActive_(True)
        bottom.trailingAnchor().constraintEqualToAnchor_(rowv.trailingAnchor()).setActive_(True)

        timer["view"] = card
        timer["card"] = card
        timer["progress"] = progress
        timer["remaining"] = remaining
        timer["name"] = name
        timer["rename"] = rename
        timer["plus1"] = plus1
        timer["plus10"] = plus10
        timer["plus60"] = plus60
        timer["cancel"] = cancel
        timer["restart"] = restart
        timer["done"] = done
        timer["actions"] = actions
        timer.setdefault("finished", False)
        self.timers.append(timer)
        self._retain.extend(actions)
        if timer["finished"]:
            self._apply_finished_style(timer)
        else:
            self._update_row(timer)
        self._update_section()

    def _make_extend_cb(self, timer, seconds):
        return lambda s: self._extend_timer(timer, seconds)

    def _make_cancel_cb(self, timer):
        return lambda s: self._cancel_timer(timer)

    def _make_restart_cb(self, timer):
        return lambda s: self._restart_timer(timer)

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
        self._clear_delivered_notification(timer.get("id"))
        self._update_section()

    def _update_row(self, timer):
        remaining = timer["end_ts"] - time.time()
        timer["remaining"].setStringValue_(fmt_remaining(remaining))
        frac = max(0.0, min(1.0, remaining / max(1, timer["duration"])))
        timer["progress"].setDoubleValue_(frac * 1000.0)
        color = NSColor.systemRedColor() if remaining <= 10 else NSColor.controlAccentColor()
        timer["remaining"].setTextColor_(color)

    def _update_section(self):
        n = len(self.timers)
        self.section_label.setStringValue_(
            "暂无进行中的计时器" if n == 0 else f"进行中 · {n}"
        )

    def systemColorsDidChange_(self, _notification):
        """Refresh custom accent-colored elements after System Settings changes."""
        for timer in self.timers:
            timer["progress"].refreshAccent()
            if not timer.get("finished"):
                self._update_row(timer)

    # -- 计时循环 ----------------------------------------------------------
    def _start_ticker(self):
        self._ticker = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, "tick:", None, True
        )

    def tick_(self, _timer):
        newly_finished = []
        for timer in self.timers:
            if timer.get("finished"):
                continue
            self._update_row(timer)
            if timer["end_ts"] - time.time() <= 0:
                newly_finished.append(timer)
        for timer in newly_finished:
            self._send_finish_notification(timer)
            timer["finished"] = True
            self._apply_finished_style(timer)
        if newly_finished:
            self._persist()
            self._update_size()

    def _apply_finished_style(self, timer):
        timer["remaining"].setStringValue_("已结束")
        timer["remaining"].setTextColor_(NSColor.systemRedColor())
        timer["progress"].setDoubleValue_(0.0)
        timer["card"].layer().setBorderWidth_(1.0)
        timer["card"].layer().setBorderColor_(
            NSColor.systemRedColor().colorWithAlphaComponent_(0.45).CGColor()
        )
        timer["plus1"].setHidden_(True)
        timer["plus10"].setHidden_(True)
        timer["plus60"].setHidden_(True)
        timer["cancel"].setHidden_(True)
        timer["restart"].setHidden_(False)
        timer["done"].setHidden_(False)

    def _apply_running_style(self, timer):
        timer["card"].layer().setBorderWidth_(0.0)
        timer["plus1"].setHidden_(False)
        timer["plus10"].setHidden_(False)
        timer["plus60"].setHidden_(False)
        timer["cancel"].setHidden_(False)
        timer["restart"].setHidden_(True)
        timer["done"].setHidden_(True)

    def _restart_timer(self, timer):
        timer["finished"] = False
        timer["end_ts"] = time.time() + timer["duration"]
        self._clear_delivered_notification(timer.get("id"))
        self._apply_running_style(timer)
        self._update_row(timer)
        self._persist()
        self._update_size()

    # -- 通知 (UNUserNotificationCenter, 从 MultiTimer.app 发出) --------------
    def _setup_notifications(self):
        if os.environ.get("MULTITIMER_DISABLE_NOTIFICATIONS") == "1":
            self.notif_center = None
            return
        try:
            center = UNUserNotificationCenter.currentNotificationCenter()
        except Exception:
            self.notif_center = None
            return
        self.notif_center = center
        center.setDelegate_(self)
        center.requestAuthorizationWithOptions_completionHandler_(
            UNAuthorizationOptionAlert | UNAuthorizationOptionSound,
            lambda granted, err: None,
        )
        check = UNNotificationAction.actionWithIdentifier_title_options_(
            _NOTIF_ACTION_CHECK, "已检查", UNNotificationActionOptionNone
        )
        category = UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
            _NOTIF_CATEGORY, [check], [], UNNotificationCategoryOptionNone
        )
        center.setNotificationCategories_({category})

    def _send_finish_notification(self, timer):
        if getattr(self, "notif_center", None) is None:
            return
        content = UNMutableNotificationContent.alloc().init()
        content.setTitle_(APP_NAME)
        content.setSubtitle_(timer["label"])
        content.setBody_("时间到, 点击 '已检查' 移除")
        content.setCategoryIdentifier_(_NOTIF_CATEGORY)
        content.setUserInfo_({"timer_id": timer["id"]})
        request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
            timer["id"], content, None
        )
        self.notif_center.addNotificationRequest_withCompletionHandler_(
            request, lambda err: None
        )

    def _clear_delivered_notification(self, timer_id):
        if not timer_id or getattr(self, "notif_center", None) is None:
            return
        self.notif_center.removeDeliveredNotificationsWithIdentifiers_([timer_id])
        self.notif_center.removePendingNotificationRequestsWithIdentifiers_([timer_id])

    def _check_by_id(self, timer_id):
        if not timer_id:
            return
        for t in list(self.timers):
            if t.get("id") == timer_id:
                self._cancel_timer(t)
                return

    # UNUserNotificationCenterDelegate ------------------------------------
    def userNotificationCenter_willPresentNotification_withCompletionHandler_(
        self, _center, _notification, completion
    ):
        completion(
            UNNotificationPresentationOptionBanner
            | UNNotificationPresentationOptionList
            | UNNotificationPresentationOptionSound
        )

    def userNotificationCenter_didReceiveNotificationResponse_withCompletionHandler_(
        self, _center, response, completion
    ):
        try:
            action_id = response.actionIdentifier()
            if action_id == _NOTIF_ACTION_CHECK:
                info = response.notification().request().content().userInfo()
                timer_id = info.get("timer_id") if info else None
                self._check_by_id(timer_id)
        finally:
            completion()

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

    def _show_preview_window(self):
        """Show the production content in a normal window for visual QA only."""
        self.content_view.layoutSubtreeIfNeeded()
        size = self.content_view.fittingSize()
        frame = NSMakeRect(0, 0, size.width, size.height)
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False
        )
        window.setTitle_(APP_NAME)
        window.setContentView_(self.content_view)
        window.center()
        window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self._preview_window = window
        snapshot_path = os.environ.get("MULTITIMER_SNAPSHOT_PATH")
        if snapshot_path:
            self._save_preview_snapshot(snapshot_path)

    def _save_preview_snapshot(self, snapshot_path):
        """Render the preview content for website and README screenshots."""
        self.content_view.setWantsLayer_(True)
        self.content_view.layer().setBackgroundColor_(NSColor.windowBackgroundColor().CGColor())
        self.content_view.layoutSubtreeIfNeeded()
        bounds = self.content_view.bounds()
        bitmap = self.content_view.bitmapImageRepForCachingDisplayInRect_(bounds)
        self.content_view.cacheDisplayInRect_toBitmapImageRep_(bounds, bitmap)
        data = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
        Path(snapshot_path).write_bytes(bytes(data))

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

    def applicationWillTerminate_(self, _notification):
        if self._did_finish_launching:
            self._persist()


def main():
    app = NSApplication.sharedApplication()
    preview = os.environ.get("MULTITIMER_PREVIEW") == "1"
    policy = NSApplicationActivationPolicyRegular if preview else NSApplicationActivationPolicyAccessory
    app.setActivationPolicy_(policy)  # 正常运行时不显示 Dock 图标
    appearance = os.environ.get("MULTITIMER_APPEARANCE", "").lower()
    if appearance in {"light", "dark"}:
        appearance_name = NSAppearanceNameDarkAqua if appearance == "dark" else NSAppearanceNameAqua
        app.setAppearance_(NSAppearance.appearanceNamed_(appearance_name))
    delegate = MultiTimerApp.alloc().init()
    app.setDelegate_(delegate)
    global _APP_DELEGATE
    _APP_DELEGATE = delegate  # 保活
    AppHelper.runEventLoop(installInterrupt=True)


if __name__ == "__main__":
    main()
