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
import hashlib
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse

import objc
from Foundation import (
    NSObject,
    NSTimer,
    NSMakeRect,
    NSMakeSize,
    NSNotificationCenter,
    NSURL,
)
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
    NSRunningApplication,
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
    NSAlert,
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
    NSWorkspace,
)

APP_NAME = "MultiTimer"
APP_VERSION = "0.3.3"
# macOS 26 can retain a broken Control Center visibility record for a status
# item even after the app is reinstalled.  Use a fresh, status-bar-specific
# identity for the production app so upgrades are not tied to that stale entry.
APP_BUNDLE_ID = "io.github.echoforger.multitimer.statusbar"
APP_COPYRIGHT = "© 2026 EchoForger"
APP_HOMEPAGE = "https://echoforger.github.io/multi-timer/"
APP_REPOSITORY = "https://github.com/EchoForger/multi-timer"
LATEST_RELEASE_URL = f"{APP_REPOSITORY}/releases/latest"
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


def _version_tuple(value: str) -> tuple:
    """Convert tags such as v0.3.2 into a tuple suitable for comparison."""
    clean = str(value).strip().lstrip("vV")
    parts = []
    for component in clean.split("."):
        digits = "".join(ch for ch in component if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts or [0])


def _release_version(release: dict) -> str:
    return str(release.get("tag_name", "")).strip().lstrip("vV")


def _select_dmg_asset(release: dict) -> dict:
    version = _release_version(release)
    assets = release.get("assets") or []
    expected = f"MultiTimer-{version}.dmg"
    for asset in assets:
        if asset.get("name") == expected:
            return asset
    for asset in assets:
        if str(asset.get("name", "")).lower().endswith(".dmg"):
            return asset
    raise RuntimeError("这个 Release 没有可用的 DMG 安装包")


def _fetch_latest_release() -> dict:
    """Resolve GitHub's public latest-release redirect without using its API.

    The unauthenticated REST API is limited per IP address and can return 403
    on otherwise healthy machines.  The normal Release URL is not tied to that
    API quota and redirects to the latest published tag.
    """
    request = urllib.request.Request(
        LATEST_RELEASE_URL,
        headers={
            "User-Agent": f"MultiTimer/{APP_VERSION}",
        },
        method="HEAD",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        resolved_url = response.geturl()
    parts = [unquote(part) for part in urlparse(resolved_url).path.split("/") if part]
    try:
        tag = parts[parts.index("tag") + 1]
    except (ValueError, IndexError) as exc:
        raise RuntimeError("无法从 GitHub Release 地址识别最新版本") from exc
    version = tag.lstrip("vV")
    if not version or _version_tuple(version) == (0,):
        raise RuntimeError("GitHub Release 没有有效的版本号")
    dmg_name = f"MultiTimer-{version}.dmg"
    return {
        "tag_name": tag,
        "html_url": resolved_url,
        "body": "该版本包含功能改进与问题修复。",
        "assets": [
            {
                "name": dmg_name,
                "browser_download_url": f"{APP_REPOSITORY}/releases/download/{tag}/{dmg_name}",
            }
        ],
    }


def _current_app_bundle_path():
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    for path in (executable, *executable.parents):
        if path.suffix.lower() == ".app" and (path / "Contents" / "MacOS").is_dir():
            return path
    return None


def _find_brew():
    candidates = [shutil.which("brew"), "/opt/homebrew/bin/brew", "/usr/local/bin/brew"]
    return next((str(Path(item)) for item in candidates if item and Path(item).is_file()), None)


def _is_homebrew_bundle(bundle_path: Path) -> bool:
    """Match the running app to Homebrew's Caskroom artifact symlink."""
    resolved = bundle_path.resolve()
    for root in (
        Path("/opt/homebrew/Caskroom/multi-timer"),
        Path("/usr/local/Caskroom/multi-timer"),
    ):
        if not root.is_dir():
            continue
        for artifact in root.glob("*/MultiTimer.app"):
            try:
                if artifact.is_symlink() and artifact.resolve() == resolved:
                    return True
            except OSError:
                continue
    return False


def _installation_source() -> str:
    """Return homebrew, dmg, or development without relying on the GUI app PATH."""
    forced = os.environ.get("MULTITIMER_INSTALL_SOURCE", "").lower()
    if forced in {"homebrew", "dmg", "development"}:
        return forced
    bundle_path = _current_app_bundle_path()
    if bundle_path is None:
        return "development"
    return "homebrew" if _is_homebrew_bundle(bundle_path) else "dmg"


def _installation_source_hint() -> str:
    """Fast, non-blocking source label for the About panel."""
    forced = os.environ.get("MULTITIMER_INSTALL_SOURCE", "").lower()
    if forced in {"homebrew", "dmg", "development"}:
        return forced
    bundle_path = _current_app_bundle_path()
    if bundle_path is None:
        return "development"
    return "homebrew" if _is_homebrew_bundle(bundle_path) else "dmg"


def _bundle_version(bundle_path: Path) -> str:
    plist_path = bundle_path / "Contents" / "Info.plist"
    with plist_path.open("rb") as stream:
        info = plistlib.load(stream)
    return str(info.get("CFBundleShortVersionString", "0"))


def _bundle_identifier(bundle_path: Path) -> str:
    plist_path = bundle_path / "Contents" / "Info.plist"
    with plist_path.open("rb") as stream:
        info = plistlib.load(stream)
    return str(info.get("CFBundleIdentifier", ""))


def _best_installed_bundle_path():
    """Find a valid installed copy even after Homebrew replaces its symlink."""
    candidates = [
        Path("/Applications/MultiTimer.app"),
        Path.home() / "Applications" / "MultiTimer.app",
    ]
    for root in (Path("/opt/homebrew/Caskroom/multi-timer"), Path("/usr/local/Caskroom/multi-timer")):
        if root.is_dir():
            candidates.extend(root.glob("*/MultiTimer.app"))
    current = _current_app_bundle_path()
    if current is not None:
        candidates.append(current)
    valid = []
    for candidate in candidates:
        try:
            if candidate.is_dir() and _bundle_identifier(candidate) == APP_BUNDLE_ID:
                valid.append((_version_tuple(_bundle_version(candidate)), candidate))
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
    if not valid:
        return None
    return max(valid, key=lambda item: item[0])[1]


def _run_checked(command, timeout, error_title):
    result = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "未知错误").strip()
        raise RuntimeError(f"{error_title}\n{detail[-1600:]}")
    return result


def _upgrade_via_homebrew(expected_version: str):
    brew = _find_brew()
    if not brew:
        raise RuntimeError("未找到 Homebrew，无法自动更新")
    _run_checked(
        [brew, "upgrade", "--cask", "--no-quit", "echoforger/multi-timer/multi-timer"],
        1200,
        "Homebrew 升级 MultiTimer 失败",
    )
    bundle_path = _best_installed_bundle_path()
    if bundle_path and _version_tuple(_bundle_version(bundle_path)) < _version_tuple(expected_version):
        # Brew may skip its automatic refresh when it updated recently. Only
        # force a source refresh when the targeted upgrade left an old build.
        _run_checked([brew, "update"], 600, "Homebrew 更新软件源失败")
        _run_checked(
            [brew, "upgrade", "--cask", "--no-quit", "echoforger/multi-timer/multi-timer"],
            1200,
            "Homebrew 升级 MultiTimer 失败",
        )
        bundle_path = _best_installed_bundle_path()
    if bundle_path and _version_tuple(_bundle_version(bundle_path)) < _version_tuple(expected_version):
        raise RuntimeError("Homebrew 已运行，但安装的 MultiTimer 仍不是最新版")


def _download_release_dmg(release: dict, destination: Path) -> Path:
    asset = _select_dmg_asset(release)
    digest = str(asset.get("digest") or "")
    if not digest.startswith("sha256:"):
        checksum_url = f"{asset.get('browser_download_url', '')}.sha256"
        if not checksum_url.startswith("https://"):
            raise RuntimeError("Release 缺少 SHA256 摘要，已取消自动安装")
        checksum_request = urllib.request.Request(
            checksum_url,
            headers={"User-Agent": f"MultiTimer/{APP_VERSION}"},
        )
        try:
            with urllib.request.urlopen(checksum_request, timeout=20) as response:
                expected = response.read(512).decode("ascii", "strict").strip().split()[0].lower()
        except Exception as exc:
            raise RuntimeError("无法获取 DMG 的 SHA256 校验值，已取消自动安装") from exc
        if len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
            raise RuntimeError("Release 的 SHA256 校验值无效，已取消自动安装")
        digest = f"sha256:{expected}"
    url = asset.get("browser_download_url")
    if not url:
        raise RuntimeError("Release 缺少 DMG 下载地址")
    request = urllib.request.Request(url, headers={"User-Agent": f"MultiTimer/{APP_VERSION}"})
    sha256 = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=60) as response, destination.open("wb") as output:
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            sha256.update(chunk)
            output.write(chunk)
    if sha256.hexdigest().lower() != digest.split(":", 1)[1].lower():
        raise RuntimeError("DMG 的 SHA256 校验失败，已取消安装")
    return destination


def _install_dmg_update(release: dict, destination=None):
    """Download, verify, stage, and atomically replace a DMG-installed app."""
    expected_version = _release_version(release)
    app_path = Path(destination) if destination else _current_app_bundle_path()
    if app_path is None or app_path.name != "MultiTimer.app":
        raise RuntimeError("当前不是可替换的 MultiTimer.app，请前往 Release 页手动安装")
    parent = app_path.parent
    token = uuid.uuid4().hex
    staged = parent / f".MultiTimer.update-{token}.app"
    backup = parent / f".MultiTimer.backup-{token}.app"
    swapped = False
    mounted = False
    with tempfile.TemporaryDirectory(prefix="multitimer-update-") as temp:
        temp_path = Path(temp)
        dmg_path = _download_release_dmg(release, temp_path / f"MultiTimer-{expected_version}.dmg")
        mount_path = temp_path / "mount"
        mount_path.mkdir()
        try:
            _run_checked(
                ["/usr/bin/hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", str(mount_path), str(dmg_path)],
                120,
                "打开 DMG 失败",
            )
            mounted = True
            source_app = mount_path / "MultiTimer.app"
            if not source_app.is_dir():
                raise RuntimeError("DMG 中没有 MultiTimer.app")
            if _version_tuple(_bundle_version(source_app)) != _version_tuple(expected_version):
                raise RuntimeError("DMG 内应用的版本与 Release 不一致")
            _run_checked(
                ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(source_app)],
                60,
                "MultiTimer.app 完整性验证失败",
            )
            _run_checked(["/usr/bin/ditto", str(source_app), str(staged)], 180, "复制新版应用失败")
            _run_checked(
                ["/usr/bin/codesign", "--verify", "--deep", "--strict", str(staged)],
                60,
                "更新缓存的应用完整性验证失败",
            )
            os.replace(app_path, backup)
            try:
                os.replace(staged, app_path)
                swapped = True
            except Exception:
                os.replace(backup, app_path)
                raise
            shutil.rmtree(backup, ignore_errors=True)
        finally:
            if mounted:
                subprocess.run(
                    ["/usr/bin/hdiutil", "detach", str(mount_path), "-force"],
                    capture_output=True,
                    timeout=60,
                    check=False,
                )
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)
            if backup.exists() and not swapped and not app_path.exists():
                os.replace(backup, app_path)



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
        self._update_in_progress = False
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

    # -- 关于 / 更新 -------------------------------------------------------
    def _app_icon(self):
        return NSImage.alloc().initWithContentsOfFile_(str(resource_path("assets/app-icon.png")))

    def _show_alert(self, title, detail="", buttons=("好",)):
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        if detail:
            alert.setInformativeText_(detail)
        icon = self._app_icon()
        if icon is not None:
            alert.setIcon_(icon)
        for button_title in buttons:
            alert.addButtonWithTitle_(button_title)
        NSApp.activateIgnoringOtherApps_(True)
        return alert.runModal()

    def _open_url(self, url):
        NSWorkspace.sharedWorkspace().openURL_(NSURL.URLWithString_(url))

    def _show_about(self):
        if self.popover.isShown():
            self.popover.close()
        source = {
            "homebrew": "Homebrew",
            "dmg": "DMG",
            "development": "开发模式",
        }.get(_installation_source_hint(), "未知")
        detail = (
            f"版本 {APP_VERSION}\n"
            f"安装来源：{source}\n\n"
            "多个倒计时，一个节奏。\n"
            "原生 macOS 菜单栏多任务倒计时器。\n\n"
            f"{APP_COPYRIGHT}\n"
            "MIT License · 无账户 · 无遥测 · 数据仅在本机"
        )
        response = self._show_alert(
            f"关于 {APP_NAME}",
            detail,
            ("检查更新", "项目主页", "关闭"),
        )
        if response == 1000:
            self._check_for_updates()
        elif response == 1001:
            self._open_url(APP_REPOSITORY)

    def _check_for_updates(self):
        if self._update_in_progress:
            self._show_alert("更新正在进行", "请稍候，MultiTimer 会在完成后通知你。")
            return
        self._update_in_progress = True
        self.status_item.button().setToolTip_("正在检查 MultiTimer 更新…")
        threading.Thread(target=self._check_update_worker, daemon=True).start()

    def _check_update_worker(self):
        try:
            release = _fetch_latest_release()
            source = _installation_source()
        except Exception as exc:
            AppHelper.callAfter(self._update_failed, f"检查更新失败\n{exc}")
            return
        AppHelper.callAfter(self._present_update, release, source)

    def _present_update(self, release, source):
        latest = _release_version(release)
        if not latest:
            self._update_failed("GitHub Release 没有有效的版本号")
            return
        if _version_tuple(latest) <= _version_tuple(APP_VERSION):
            self._update_in_progress = False
            self.status_item.button().setToolTip_(APP_NAME)
            self._show_alert("已是最新版", f"你正在使用 MultiTimer {APP_VERSION}。")
            return

        notes = str(release.get("body") or "该版本包含功能改进与问题修复。").strip()
        if len(notes) > 900:
            notes = notes[:897] + "…"
        if source == "homebrew":
            self.status_item.button().setToolTip_(f"正在通过 Homebrew 更新到 {latest}…")
            threading.Thread(target=self._brew_update_worker, args=(latest,), daemon=True).start()
            return
        if source == "dmg":
            self._update_in_progress = False
            self.status_item.button().setToolTip_(APP_NAME)
            response = self._show_alert(
                f"发现 MultiTimer {latest}",
                f"当前版本：{APP_VERSION}\n\n{notes}\n\n是否下载、校验并安装更新？",
                ("下载并安装", "稍后"),
            )
            if response == 1000:
                self._update_in_progress = True
                self.status_item.button().setToolTip_(f"正在安装 MultiTimer {latest}…")
                threading.Thread(
                    target=self._dmg_update_worker,
                    args=(release, latest),
                    daemon=True,
                ).start()
            return

        self._update_in_progress = False
        self.status_item.button().setToolTip_(APP_NAME)
        response = self._show_alert(
            f"发现 MultiTimer {latest}",
            f"当前正在开发模式中运行，不会覆盖源码。\n\n{notes}",
            ("打开 Release 页", "稍后"),
        )
        if response == 1000:
            self._open_url(str(release.get("html_url") or f"{APP_REPOSITORY}/releases/latest"))

    def _brew_update_worker(self, latest):
        try:
            _upgrade_via_homebrew(latest)
        except Exception as exc:
            AppHelper.callAfter(self._update_failed, str(exc))
            return
        AppHelper.callAfter(self._update_succeeded, latest, "Homebrew")

    def _dmg_update_worker(self, release, latest):
        try:
            _install_dmg_update(release)
        except Exception as exc:
            AppHelper.callAfter(self._update_failed, str(exc))
            return
        AppHelper.callAfter(self._update_succeeded, latest, "DMG")

    def _update_failed(self, detail):
        self._update_in_progress = False
        self.status_item.button().setToolTip_(APP_NAME)
        response = self._show_alert("更新未完成", detail, ("好", "打开 Release 页"))
        if response == 1001:
            self._open_url(f"{APP_REPOSITORY}/releases/latest")

    def _update_succeeded(self, latest, source):
        self._update_in_progress = False
        self.status_item.button().setToolTip_(APP_NAME)
        response = self._show_alert(
            "更新已安装",
            f"MultiTimer {latest} 已通过 {source} 安装完成。重新启动后生效。",
            ("现在重新启动", "稍后"),
        )
        if response == 1000:
            self._relaunch()

    def _relaunch(self):
        bundle_path = _best_installed_bundle_path()
        if bundle_path is None:
            return
        self._persist()
        subprocess.Popen(
            [
                "/bin/sh",
                "-c",
                "sleep 1; exec /usr/bin/open -n \"$1\"",
                "multitimer-relaunch",
                str(bundle_path),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
            close_fds=True,
        )
        NSApp.terminate_(None)

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
        about_btn = _button("ⓘ", lambda s: self._show_about(), self._retain, small=True, quiet=True)
        about_btn.setToolTip_(f"关于 {APP_NAME}")
        header.addArrangedSubview_(about_btn)
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
    if not preview:
        current_pid = os.getpid()
        running = NSRunningApplication.runningApplicationsWithBundleIdentifier_(APP_BUNDLE_ID)
        if any(candidate.processIdentifier() != current_pid for candidate in running):
            # A menu-bar app has no window to activate.  Keeping exactly one
            # instance also prevents duplicate status-item hosts in Control
            # Center, which can otherwise make macOS hide both of them.
            return
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
