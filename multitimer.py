#!/usr/bin/env python3
"""MultiTimer - 多路倒计时小工具 (macOS 原生菜单栏应用)

使用 AppKit (PyObjC) 原生组件:
- 常驻菜单栏 NSStatusItem, 点击弹出 NSPopover (系统毛玻璃, 跟随深/浅色)
- 原生 NSSlider / NSTextField / NSButton, 跟随系统强调色
- 不在 Dock 显示 (ActivationPolicy = Accessory)
- 输入任务名 + 拉杆选择时长, 或直接填写目标时间即开始; 可并行多个倒计时
- 每条记录只保存开始时间和结束时间; 未填任务名时自动使用 "任务 N"
- 每行的剩余时间和目标时间都可点击直接编辑; 任务名单行省略、可原生行内改名
- 到点由 MultiTimer.app 通过 UNUserNotificationCenter 发出可交互通知
  (点击 "已检查" 按钮 => 直接从列表中移除对应倒计时)
"""

import csv
import datetime
import fcntl
import io
import json
import hashlib
import math
import os
import plistlib
import socket
import socketserver
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
import uuid
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import xml.etree.ElementTree as ET
from html import escape as html_escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import objc
from Foundation import (
    NSObject,
    NSTimer,
    NSMakeRect,
    NSMakeRange,
    NSMakeSize,
    NSNotificationCenter,
    NSAppleEventManager,
    NSBundle,
    NSLocale,
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
    UNAuthorizationStatusDenied,
    UNAuthorizationStatusNotDetermined,
)
from AppKit import (
    NSApplication,
    NSApp,
    NSRunningApplication,
    NSApplicationActivationPolicyAccessory,
    NSApplicationActivationPolicyRegular,
    NSStatusBar,
    NSStatusItemBehaviorTerminationOnRemoval,
    NSSquareStatusItemLength,
    NSVariableStatusItemLength,
    NSMenu,
    NSMenuItem,
    NSImage,
    NSBezierPath,
    NSPopover,
    NSPopoverBehaviorTransient,
    NSPopoverBehaviorApplicationDefined,
    NSViewController,
    NSView,
    NSImageView,
    NSImageScaleProportionallyUpOrDown,
    NSStackView,
    NSSlider,
    NSTextField,
    NSButton,
    NSAlert,
    NSBox,
    NSBoxSeparator,
    NSColor,
    NSSound,
    NSEvent,
    NSEventMaskKeyDown,
    NSEventModifierFlagCommand,
    NSEventModifierFlagShift,
    NSFont,
    NSFontWeightBold,
    NSFontWeightMedium,
    NSFontWeightSemibold,
    NSUserInterfaceLayoutOrientationVertical,
    NSUserInterfaceLayoutOrientationHorizontal,
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
    NSControlStateValueOn,
    NSControlStateValueOff,
    NSSwitchButton,
    NSImageLeft,
    NSImageOnly,
)

APP_NAME = "MultiTimer"
APP_VERSION = "0.6.0"
# Keep one stable identity across installs, login items, notifications,
# URL handling, and Control Center status-item restoration.
APP_BUNDLE_ID = "io.github.echoforger.multitimer"
STATUS_ITEM_AUTOSAVE_NAME = f"{APP_BUNDLE_ID}.primary"
APP_COPYRIGHT = "© 2026 EchoForger"
APP_HOMEPAGE = "https://echoforger.github.io/multi-timer/"
APP_REPOSITORY = "https://github.com/EchoForger/multi-timer"
LATEST_RELEASE_URL = f"{APP_REPOSITORY}/releases/latest"
RELEASES_FEED_URL = f"{APP_REPOSITORY}/releases.atom"
STATE_PATH = Path(
    os.environ.get(
        "MULTITIMER_STATE_PATH",
        str(Path.home() / ".config" / "multitimer" / "state.json"),
    )
)
PANEL_WIDTH = 296
CONTROL_SOCKET_PATH = STATE_PATH.parent / "control.sock"
CONTROL_LOCK_PATH = STATE_PATH.parent / "control.lock"
POMODORO_STATS_PATH = STATE_PATH.parent / "pomodoro-stats.json"
MAX_DURATION_SECONDS = 24 * 3600
POMODORO_MAX_SECONDS = 59 * 60 + 59
DEFAULT_DURATION_SECONDS = 300

DEFAULT_SETTINGS = {
    "show_remaining": False,
    "show_count": False,
    "sort_by_expiry": True,
    "pomodoro_work_seconds": 25 * 60,
    "pomodoro_break_seconds": 5 * 60,
    "pomodoro_auto_cycle": False,
    "show_pomodoro": True,
    "sync_revision": 0.0,
}

STRINGS = {
    "zh": {
        "timer_name": "计时名称（可选）", "duration": "时长", "ends_at": "结束",
        "target_time": "目标时间", "start": "开始", "stopwatch": "秒表",
        "empty": "暂无进行中的计时器", "running": "进行中 · {count}",
        "task": "任务 {number}", "rename_tip": "双击或用力按压以重命名",
        "edit_remaining_tip": "点击编辑剩余时间，例如 16 表示 16 分钟",
        "edit_target_tip": "点击编辑目标时间，例如 21:30",
        "pomodoro": "番茄钟", "pomodoro_ready": "准备开始专注",
        "pomodoro_work": "专注中", "pomodoro_break": "休息中",
        "pomodoro_next": "休息完成", "pomodoro_start": "开始工作",
        "pomodoro_pause": "暂停", "pomodoro_resume": "继续",
        "pomodoro_skip": "立即休息", "pomodoro_stop": "停止",
        "pomodoro_work_duration": "工作时长", "pomodoro_break_duration": "休息时长",
        "pomodoro_auto_cycle": "休息后自动开始下一轮工作",
        "pomodoro_work_done": "工作结束", "pomodoro_break_started": "开始休息 {minutes} 分钟",
        "pomodoro_break_done": "休息结束", "pomodoro_work_started": "开始下一轮工作",
        "pomodoro_waiting": "准备好后开始下一轮工作",
        "pomodoro_today": "今日完成 {count} 个", "pomodoro_skip_break": "跳过休息",
        "show_pomodoro": "显示番茄钟模块", "pomodoro_stats": "查看专注统计",
        "pomodoro_extend": "延长 5 分钟",
        "restart": "重新计时", "checked": "✓ 已检查", "finished": "已结束",
        "pause": "暂停", "resume": "继续", "lap": "计圈", "laps": "{count} 圈 · 最近 {latest}",
        "duplicate": "复制", "pin": "置顶", "unpin": "取消置顶",
        "settings": "设置", "quit": "退出 MultiTimer", "about": "关于 MultiTimer",
        "notification_denied": "通知已关闭，计时结束时可能无法提醒。", "open_settings": "打开系统设置",
        "settings_title": "MultiTimer 设置", "launch_at_login": "登录时自动启动",
        "show_remaining": "菜单栏显示最近剩余时间", "show_count": "菜单栏显示计时器数量",
        "sort_by_expiry": "最近到期优先", "language": "应用语言",
        "language_detail": "由 macOS 管理。", "open_language_settings": "系统设置…",
        "back": "返回",
        "time_up_body": "时间到，点击“已检查”移除", "time_up": "时间到",
        "status_hidden": "菜单栏图标没有显示",
        "status_hidden_detail": "MultiTimer 已尝试恢复图标。若仍未显示，请在系统设置的控制中心中允许 MultiTimer 显示在菜单栏。",
        "retry": "重新创建图标", "later": "稍后", "notification_request": "允许通知",
        "source": "安装来源：{source}", "version": "版本 {version}", "development": "开发模式", "unknown": "未知",
        "tagline": "多个倒计时，一个节奏。\n原生 macOS 菜单栏多任务倒计时器。",
        "privacy": "MIT License · 无账户 · 无遥测 · 默认本地，可选 iCloud KVS 同步设置与聚合统计",
        "check_updates": "检查更新", "homepage": "项目主页", "close": "关闭",
        "update_busy": "更新正在进行", "update_busy_detail": "请稍候，MultiTimer 会在完成后通知你。",
        "checking": "正在检查 MultiTimer 更新…", "check_failed": "检查更新失败",
        "latest": "已是最新版", "latest_detail": "你正在使用 MultiTimer {version}。",
        "found_update": "发现 MultiTimer {version}", "current_version": "当前版本：{version}", "whats_new": "新版特性",
        "update_now": "立即更新", "skip_version": "跳过这个版本", "brew_will_run": "Homebrew 将在后台运行：",
        "update_failed": "更新未完成", "release_page": "打开 Release 页", "update_installed": "更新已安装",
        "update_installed_detail": "MultiTimer {version} 已通过 {source} 安装完成。重新启动后生效。",
        "restart_now": "现在重新启动",
    },
    "en": {
        "timer_name": "Timer name (optional)", "duration": "Duration", "ends_at": "Ends",
        "target_time": "Target time", "start": "Start", "stopwatch": "Stopwatch",
        "empty": "No active timers", "running": "Active · {count}",
        "task": "Timer {number}", "rename_tip": "Double-click or Force Click to rename",
        "edit_remaining_tip": "Click to edit the remaining time, e.g. 16 means 16 minutes",
        "edit_target_tip": "Click to edit the target time, e.g. 21:30",
        "pomodoro": "Pomodoro", "pomodoro_ready": "Ready to focus",
        "pomodoro_work": "Focusing", "pomodoro_break": "On a break",
        "pomodoro_next": "Break complete", "pomodoro_start": "Start Work",
        "pomodoro_pause": "Pause", "pomodoro_resume": "Resume",
        "pomodoro_skip": "Start Break", "pomodoro_stop": "Stop",
        "pomodoro_work_duration": "Work duration", "pomodoro_break_duration": "Break duration",
        "pomodoro_auto_cycle": "Automatically start work after each break",
        "pomodoro_work_done": "Work complete", "pomodoro_break_started": "Starting a {minutes}-minute break",
        "pomodoro_break_done": "Break complete", "pomodoro_work_started": "Starting the next work session",
        "pomodoro_waiting": "Start the next work session when ready",
        "pomodoro_today": "{count} completed today", "pomodoro_skip_break": "Skip Break",
        "show_pomodoro": "Show Pomodoro module", "pomodoro_stats": "View Focus Statistics",
        "pomodoro_extend": "Extend 5 Minutes",
        "restart": "Restart", "checked": "✓ Done", "finished": "Finished",
        "pause": "Pause", "resume": "Resume", "lap": "Lap", "laps": "{count} laps · latest {latest}",
        "duplicate": "Duplicate", "pin": "Pin", "unpin": "Unpin",
        "settings": "Settings", "quit": "Quit MultiTimer", "about": "About MultiTimer",
        "notification_denied": "Notifications are off, so completed timers may not alert you.", "open_settings": "Open Settings",
        "settings_title": "MultiTimer Settings", "launch_at_login": "Launch at Login",
        "show_remaining": "Show nearest remaining time", "show_count": "Show active timer count",
        "sort_by_expiry": "Sort by nearest expiry", "language": "App Language",
        "language_detail": "Managed by macOS.", "open_language_settings": "System Settings…",
        "back": "Back",
        "time_up_body": "Time is up. Click Done to remove it.", "time_up": "Time's up",
        "status_hidden": "Menu bar icon is not visible",
        "status_hidden_detail": "MultiTimer tried to restore its icon. If it is still missing, allow MultiTimer in System Settings > Control Center.",
        "retry": "Recreate Icon", "later": "Later", "notification_request": "Allow Notifications",
        "source": "Install source: {source}", "version": "Version {version}", "development": "Development", "unknown": "Unknown",
        "tagline": "Multiple timers, one rhythm.\nA native macOS menu bar timer.",
        "privacy": "MIT License · No account · No telemetry · Local by default; optional iCloud KVS sync",
        "check_updates": "Check for Updates", "homepage": "Project Home", "close": "Close",
        "update_busy": "Update in Progress", "update_busy_detail": "MultiTimer will notify you when it finishes.",
        "checking": "Checking for MultiTimer updates…", "check_failed": "Update Check Failed",
        "latest": "You're Up to Date", "latest_detail": "You're using MultiTimer {version}.",
        "found_update": "MultiTimer {version} is Available", "current_version": "Current version: {version}", "whats_new": "What's New",
        "update_now": "Update Now", "skip_version": "Skip This Version", "brew_will_run": "Homebrew will run in the background:",
        "update_failed": "Update Not Completed", "release_page": "Open Release Page", "update_installed": "Update Installed",
        "update_installed_detail": "MultiTimer {version} was installed via {source}. Restart to use it.",
        "restart_now": "Restart Now",
    },
}


def _system_language() -> str:
    try:
        preferred = list(NSLocale.preferredLanguages())
        if preferred and str(preferred[0]).lower().startswith("zh"):
            return "zh"
    except Exception:
        pass
    return "en"


def _language_for_settings(settings: dict) -> str:
    # Per-app language is managed by macOS in Language & Region. NSLocale
    # reflects that application-specific choice at the next launch.
    return _system_language()


def _status_item_autosave_name() -> str:
    """Keep production and source builds from sharing Control Center state."""
    if getattr(sys, "frozen", False):
        return STATUS_ITEM_AUTOSAVE_NAME
    return f"{STATUS_ITEM_AUTOSAVE_NAME}.development"


def _parse_multitimer_url(value: str) -> dict:
    parsed = urlparse(str(value))
    if parsed.scheme.lower() != "multitimer":
        raise ValueError("URL scheme must be multitimer")
    command = (parsed.netloc or parsed.path.lstrip("/")).lower()
    path = parsed.path.strip("/").lower()
    query = parse_qs(parsed.query)
    if command == "pomodoro":
        action = path or str(query.get("action", ["start"])[0]).lower()
        if action not in {"start", "pause", "skip", "stop", "status"}:
            raise ValueError("Unsupported Pomodoro URL action")
        return {"command": "pomodoro", "action": action}
    if command != "start":
        raise ValueError("Unsupported MultiTimer URL command")
    name = str(query.get("name", [""])[0]).strip()
    if "stopwatch" in query or str(query.get("mode", [""])[0]).lower() == "stopwatch":
        return {"command": "start", "kind": "stopwatch", "name": name}
    try:
        seconds = float(query.get("seconds", [0])[0])
        if seconds <= 0:
            seconds = float(query.get("minutes", [0])[0]) * 60
    except (TypeError, ValueError):
        seconds = 0
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("A positive finite minutes or seconds value is required")
    seconds = min(MAX_DURATION_SECONDS, int(round(seconds)))
    return {"command": "start", "kind": "countdown", "name": name, "seconds": seconds}


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
    """Return a release tag without its optional v prefix."""
    return str(release.get("tag_name", "")).strip().lstrip("vV")


def _select_dmg_asset(release: dict) -> dict:
    """Select the versioned DMG asset from a GitHub release."""
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


class _ReleaseNotesParser(HTMLParser):
    """Convert GitHub's release-note HTML into compact alert-friendly text."""

    _BLOCKS = {"h1", "h2", "h3", "p", "ul", "ol", "li", "br"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts = []

    def handle_starttag(self, tag, _attrs):
        if tag == "li":
            self._parts.append("\n• ")
        elif tag in self._BLOCKS:
            self._parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._BLOCKS:
            self._parts.append("\n")

    def handle_data(self, data):
        self._parts.append(data)

    def text(self):
        lines = []
        for line in "".join(self._parts).splitlines():
            cleaned = " ".join(line.split())
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)


def _fetch_release_notes(tag: str) -> str:
    """Read release notes from GitHub Releases' public Atom feed."""
    request = urllib.request.Request(
        RELEASES_FEED_URL,
        headers={"User-Agent": f"MultiTimer/{APP_VERSION}"},
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        root = ET.fromstring(response.read())
    namespace = {"atom": "http://www.w3.org/2005/Atom"}
    for entry in root.findall("atom:entry", namespace):
        entry_id = str(entry.findtext("atom:id", default="", namespaces=namespace))
        if not entry_id.endswith(f"/{tag}"):
            continue
        content = entry.findtext("atom:content", default="", namespaces=namespace)
        parser = _ReleaseNotesParser()
        parser.feed(content)
        notes = parser.text().strip()
        if notes:
            return notes
    return "该版本包含功能改进与问题修复。"


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
    try:
        notes = _fetch_release_notes(tag)
    except Exception:
        notes = "该版本包含功能改进与问题修复。"
    dmg_name = f"MultiTimer-{version}.dmg"
    return {
        "tag_name": tag,
        "html_url": resolved_url,
        "body": notes,
        "assets": [
            {
                "name": dmg_name,
                "browser_download_url": f"{APP_REPOSITORY}/releases/download/{tag}/{dmg_name}",
            }
        ],
    }


def _current_app_bundle_path():
    """Return the enclosing app bundle for a frozen executable."""
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    for path in (executable, *executable.parents):
        if path.suffix.lower() == ".app" and (path / "Contents" / "MacOS").is_dir():
            return path
    return None


def _can_use_user_notifications() -> bool:
    """Return whether this process has a valid application bundle identity."""
    return (
        os.environ.get("MULTITIMER_DISABLE_NOTIFICATIONS") != "1"
        and _current_app_bundle_path() is not None
    )


def _has_launchservices_identity() -> bool:
    """Return whether this frozen GUI was launched as its own macOS app."""
    service_name = os.environ.get("XPC_SERVICE_NAME", "")
    return service_name.startswith(f"application.{APP_BUNDLE_ID}.")


def _relaunch_via_launchservices_if_needed() -> bool:
    """Avoid macOS 26 assigning our status item to the parent application.

    Directly executing Contents/MacOS/MultiTimer inherits the terminal or
    automation host's XPC identity. Control Center can then persist MultiTimer's
    menu item under that foreign app and hide it when the foreign app is not
    allowed in the menu bar. LaunchServices gives the process its own identity.
    """
    if not getattr(sys, "frozen", False) or _has_launchservices_identity():
        return False
    bundle_path = _current_app_bundle_path()
    if bundle_path is None:
        return False
    command = ["/usr/bin/open", "-n", "-g"]
    for key in (
        "MULTITIMER_STATE_PATH",
        "MULTITIMER_DISABLE_NOTIFICATIONS",
        "MULTITIMER_INSTALL_SOURCE",
        "MULTITIMER_APPEARANCE",
        "MULTITIMER_PREVIEW",
        "MULTITIMER_PREVIEW_VIEW",
        "MULTITIMER_SNAPSHOT_PATH",
    ):
        if key in os.environ:
            command.extend(["--env", f"{key}={os.environ[key]}"])
    command.append(str(bundle_path))
    try:
        result = subprocess.run(command, timeout=10, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return result.returncode == 0


def _find_brew():
    """Find Homebrew outside the limited GUI application PATH."""
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
    """Run a command and raise a readable error when it fails."""
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
def split_time(seconds: float) -> tuple:
    """Split a duration into displayable fields.

    Args:
        seconds: Duration in seconds.

    Returns:
        A tuple containing hours, minutes, and seconds.
    """
    total = max(0, min(MAX_DURATION_SECONDS, int(round(seconds))))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return hours, minutes, seconds


def join_time(hours: int, minutes: int, seconds: int) -> int:
    """Combine time fields into seconds.

    Args:
        hours: Non-negative hour field.
        minutes: Minute field from zero through 59.
        seconds: Second field from zero through 59.

    Returns:
        The combined duration, capped at 24 hours.

    Raises:
        ValueError: If any field is outside its valid range.
    """
    values = (int(hours), int(minutes), int(seconds))
    if values[0] < 0 or not 0 <= values[1] <= 59 or not 0 <= values[2] <= 59:
        raise ValueError("Time fields are outside their valid ranges")
    return min(MAX_DURATION_SECONDS, values[0] * 3600 + values[1] * 60 + values[2])


def slider_position_for_seconds(seconds: float) -> float:
    """Map a duration to an exponential slider position.

    Args:
        seconds: Duration in seconds.

    Returns:
        A normalised slider position from zero through one.
    """
    ratio = max(0.0, min(1.0, float(seconds) / MAX_DURATION_SECONDS))
    return ratio ** (1.0 / 3.0)


def seconds_for_slider_position(position: float) -> int:
    """Map a slider position to a slow-then-fast duration curve.

    Args:
        position: Normalised slider position from zero through one.

    Returns:
        The corresponding duration in seconds.
    """
    normalised = max(0.0, min(1.0, float(position)))
    return int(round(MAX_DURATION_SECONDS * normalised ** 3))


def time_segment_for_position(position: float, width: float) -> int:
    """Find a time segment at a horizontal position.

    Args:
        position: Horizontal position inside the field.
        width: Total field width.

    Returns:
        Zero for hours, one for minutes, or two for seconds.
    """
    segment_width = max(1.0, float(width)) / 3.0
    return min(2, max(0, int(float(position) / segment_width)))


def time_segment_range(segment: int) -> tuple:
    """Return the two-character selection range for a time segment.

    Args:
        segment: Hour, minute, or second segment index.

    Returns:
        The text selection location and length.
    """
    bounded = min(2, max(0, int(segment)))
    return bounded * 3, 2


def replace_time_segment_digit(text: str, segment: int, digit: str, index: int) -> str:
    """Replace one digit in a fixed HH:MM:SS time string."""
    location, _length = time_segment_range(segment)
    values = list(str(text).zfill(8)[-8:])
    if index == 0:
        values[location] = "0"
        values[location + 1] = digit
    else:
        values[location] = values[location + 1]
        values[location + 1] = digit
    return "".join(values)


def fmt_remaining(seconds: float) -> str:
    hours, minutes, seconds = split_time(seconds)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def fmt_status_remaining(seconds: float) -> str:
    """Format menu-bar time without seconds using a stable HH:MM width."""
    total_minutes = max(0, int(math.ceil(max(0.0, float(seconds)) / 60.0)))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def fmt_pomodoro_remaining(seconds: float) -> str:
    """Format a Pomodoro countdown as fixed-width MM:SS."""
    total = max(0, min(POMODORO_MAX_SECONDS, int(math.ceil(float(seconds)))))
    minutes, remaining_seconds = divmod(total, 60)
    return f"{minutes:02d}:{remaining_seconds:02d}"


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds % 60 == 0:
        return f"{seconds // 60}min"
    return fmt_remaining(seconds)


def fmt_clock_time(timestamp: float) -> str:
    """Format an absolute timestamp as a local 24-hour HH:MM:SS label."""
    return time.strftime("%H:%M:%S", time.localtime(float(timestamp)))


def parse_duration_text(text: str) -> int:
    """Parse a typed length into seconds.

    A bare number is minutes, so typing 16 over "01:00" gives 16:00. Two
    colon-separated parts are MM:SS and three are HH:MM:SS.
    """
    cleaned = str(text).replace("：", ":").replace(" ", "").strip()
    if not cleaned:
        raise ValueError("Duration is empty")
    parts = cleaned.split(":")
    if len(parts) > 3 or any(not part for part in parts):
        raise ValueError("Duration must look like 16, 16:30, or 1:16:30")
    try:
        values = [float(part) for part in parts]
    except ValueError as exc:
        raise ValueError("Duration must contain numbers only") from exc
    if any(not math.isfinite(value) for value in values):
        raise ValueError("Duration must contain finite numbers only")
    if any(value < 0 for value in values):
        raise ValueError("Duration must not be negative")
    if len(values) == 1:
        seconds = values[0] * 60
    elif len(values) == 2:
        seconds = values[0] * 60 + values[1]
    else:
        seconds = values[0] * 3600 + values[1] * 60 + values[2]
    return min(MAX_DURATION_SECONDS, int(round(seconds)))


def parse_clock_text(text: str, now: float) -> float:
    """Parse a typed 24-hour time into the next matching absolute timestamp."""
    cleaned = str(text).replace("：", ":").replace(" ", "").strip()
    if not cleaned:
        raise ValueError("Target time is empty")
    parts = cleaned.split(":")
    if len(parts) == 1:
        digits = parts[0]
        if not digits.isdigit():
            raise ValueError("Target time must look like 21:30:00")
        if len(digits) <= 2:
            hour, minute, second = int(digits), 0, 0
        elif len(digits) <= 4:
            hour, minute, second = int(digits[:-2]), int(digits[-2:]), 0
        elif len(digits) <= 6:
            hour = int(digits[:-4])
            minute = int(digits[-4:-2])
            second = int(digits[-2:])
        else:
            raise ValueError("Target time must look like 21:30:00")
    elif len(parts) in {2, 3} and all(part.isdigit() for part in parts):
        hour, minute = int(parts[0]), int(parts[1])
        second = int(parts[2]) if len(parts) == 3 else 0
    else:
        raise ValueError("Target time must look like 21:30:00")
    if hour > 23 or minute > 59 or second > 59:
        raise ValueError("Target time is outside 00:00:00-23:59:59")
    base = datetime.datetime.fromtimestamp(now)
    target = base.replace(hour=hour, minute=minute, second=second, microsecond=0)
    if target.timestamp() <= now:
        target += datetime.timedelta(days=1)
    return target.timestamp()


# ---------------------------------------------------------------------------
# 每条记录只保存开始时间与结束时间, 其余状态都由它们推导
# ---------------------------------------------------------------------------
def timer_is_paused(timer: dict) -> bool:
    return float(timer.get("paused_at") or 0) > 0


def timer_reference_time(timer: dict) -> float:
    """Return the moment a paused timer froze at, or the current time."""
    return float(timer.get("paused_at") or 0) or time.time()


def timer_remaining(timer: dict) -> float:
    if timer.get("kind", "countdown") != "countdown":
        return 0.0
    return max(0.0, float(timer.get("end_ts") or 0) - timer_reference_time(timer))


def timer_elapsed(timer: dict) -> float:
    return max(0.0, timer_reference_time(timer) - float(timer.get("start_ts") or 0))


def timer_duration(timer: dict) -> float:
    if timer.get("kind", "countdown") != "countdown":
        return 0.0
    return max(0.0, float(timer.get("end_ts") or 0) - float(timer.get("start_ts") or 0))


def timer_display_seconds(timer: dict) -> float:
    return timer_elapsed(timer) if timer.get("kind") == "stopwatch" else timer_remaining(timer)


def pomodoro_remaining(pomodoro: dict, now=None) -> float:
    """Return the remaining seconds for an active Pomodoro stage."""
    if pomodoro.get("phase") not in {"work", "break"}:
        return 0.0
    reference = float(pomodoro.get("paused_at") or 0) or float(now or time.time())
    return max(0.0, float(pomodoro.get("end_ts") or 0) - reference)


def next_pomodoro_phase(phase: str, auto_cycle: bool) -> str:
    """Return the phase entered after the current stage completes."""
    if phase == "work":
        return "break"
    if phase == "break":
        return "work" if auto_cycle else "ready"
    return "idle"


_NOTIF_CATEGORY = "TIMER_DONE"
_NOTIF_ACTION_CHECK = "MARK_CHECKED"
_POMODORO_NOTIF_CATEGORY = "POMODORO_DONE"
_POMODORO_ACTION_EXTEND = "POMODORO_EXTEND_5"


def _normalise_timer(raw: dict, now: float) -> dict:
    """Convert any stored record into the start/end representation."""
    timer = {
        "id": str(raw.get("id") or uuid.uuid4().hex),
        "label": str(raw.get("label") or ""),
        "kind": "stopwatch" if raw.get("kind") == "stopwatch" else "countdown",
        "pinned": bool(raw.get("pinned")),
        "finished": bool(raw.get("finished")),
        "laps": [float(value) for value in (raw.get("laps") or [])],
    }
    paused_at = float(raw.get("paused_at") or 0)
    paused = paused_at > 0 or bool(raw.get("paused"))
    if timer["kind"] == "stopwatch":
        if "elapsed_before" in raw and paused_at <= 0:
            elapsed = float(raw.get("elapsed_before") or 0)
            if not paused:
                elapsed += max(0.0, now - float(raw.get("start_ts") or now))
            start_ts = now - elapsed
        else:
            start_ts = float(raw.get("start_ts") or now)
        timer.update({
            "start_ts": start_ts,
            "end_ts": 0.0,
            "paused_at": paused_at or (now if paused else 0.0),
        })
        return timer
    end_ts = float(raw.get("end_ts") or 0)
    duration = float(raw.get("duration") or 0)
    start_ts = float(raw.get("start_ts") or 0)
    if paused and paused_at <= 0 and "paused_remaining" in raw:
        # Older files froze the remaining time instead of the pause moment, so
        # their end_ts is stale and the length has to come from duration.
        end_ts = now + max(0.0, float(raw.get("paused_remaining") or 0))
        paused_at = now
        start_ts = end_ts - duration if duration > 0 else 0.0
    if start_ts <= 0:
        start_ts = float(raw.get("created_ts") or 0) or end_ts - duration
    timer.update({
        "start_ts": min(start_ts, end_ts),
        "end_ts": end_ts,
        "paused_at": paused_at or (now if paused else 0.0),
    })
    return timer


def load_state() -> dict:
    """Load valid persisted state while isolating damaged records."""
    default = {"timers": [], "settings": dict(DEFAULT_SETTINGS), "skipped_update": ""}
    if not STATE_PATH.exists():
        return default
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return default
    if not isinstance(data, dict):
        return default
    now = time.time()
    timers = []
    raw_timers = data.get("timers", [])
    if not isinstance(raw_timers, list):
        raw_timers = []
    for raw in raw_timers:
        if not isinstance(raw, dict):
            continue
        try:
            timer = _normalise_timer(raw, now)
        except (TypeError, ValueError, OverflowError):
            continue
        if timer["kind"] == "stopwatch":
            timers.append(timer)
        elif timer_is_paused(timer) or timer["finished"] or timer["end_ts"] > now:
            timers.append(timer)
    settings = dict(DEFAULT_SETTINGS)
    raw_settings = data.get("settings") or {}
    if isinstance(raw_settings, dict):
        settings.update({key: value for key, value in raw_settings.items() if key in settings})
    return {
        "timers": timers,
        "settings": settings,
        "skipped_update": str(data.get("skipped_update") or ""),
    }


def _persistent_timer(timer: dict) -> dict:
    keys = (
        "id", "label", "kind", "start_ts", "end_ts", "paused_at",
        "pinned", "finished", "laps",
    )
    return {key: timer[key] for key in keys if key in timer}


def _atomic_write_json(path: Path, payload: dict) -> None:
    """Atomically write a JSON document to disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(payload, ensure_ascii=False, indent=2)
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def load_pomodoro_stats(path=None) -> dict:
    """Load valid daily completed-Pomodoro counts."""
    stats_path = Path(path or POMODORO_STATS_PATH)
    try:
        raw = json.loads(stats_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    if not isinstance(raw, dict):
        return {}
    stats = {}
    for day, count in raw.items():
        if not isinstance(day, str) or not isinstance(count, (int, float)):
            continue
        if isinstance(count, bool) or not math.isfinite(float(count)):
            continue
        try:
            stats[day] = max(0, int(count))
        except (OverflowError, ValueError):
            continue
    return stats


def save_pomodoro_stats(stats: dict, path=None) -> None:
    """Persist daily completed-Pomodoro counts atomically."""
    stats_path = Path(path or POMODORO_STATS_PATH)
    _atomic_write_json(stats_path, stats)


def pomodoro_stats_last_days(stats: dict, days=30, today=None) -> list:
    """Return a dense local-date series for the requested number of days."""
    end = today or datetime.date.today()
    return [
        {
            "date": (end - datetime.timedelta(days=offset)).isoformat(),
            "count": int(stats.get((end - datetime.timedelta(days=offset)).isoformat(), 0)),
        }
        for offset in reversed(range(days))
    ]


def pomodoro_stats_csv(stats: dict, days=30, today=None) -> str:
    """Return a CSV export of the dense statistics series."""
    stream = io.StringIO()
    writer = csv.writer(stream)
    writer.writerow(("date", "completed_pomodoros"))
    for item in pomodoro_stats_last_days(stats, days, today):
        writer.writerow((item["date"], item["count"]))
    return stream.getvalue()


def save_state(timers: list, skipped_update="", settings=None) -> None:
    """Atomically persist state without exposing a partial JSON document."""
    payload = {
        "schema_version": 3,
        "timers": [_persistent_timer(timer) for timer in timers],
        "skipped_update": skipped_update,
        "settings": dict(settings or DEFAULT_SETTINGS),
    }
    _atomic_write_json(STATE_PATH, payload)


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


class _ControlHandler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            request = json.loads(self.rfile.readline(65536).decode("utf-8"))
            response = self.server.app.handle_cli_request(request)
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        self.wfile.write((json.dumps(response, ensure_ascii=False) + "\n").encode("utf-8"))


class _ControlServer(socketserver.ThreadingUnixStreamServer):
    daemon_threads = True
    allow_reuse_address = True

    def get_request(self):
        request, client_address = super().get_request()
        request.settimeout(3)
        return request, client_address


def pomodoro_stats_html(series: list, token: str) -> str:
    """Render the local-only Pomodoro statistics page."""
    bars = "".join(
        f'<div class="day"><div class="bar" style="height:{0 if item["count"] == 0 else max(3, item["count"] * 18)}px"></div>'
        f'<span>{html_escape(item["date"][5:])}</span>'
        f'<b>{html_escape(str(item["count"]))}</b></div>'
        for item in series
    )
    total = sum(item["count"] for item in series)
    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<title>MultiTimer 专注统计</title><style>
body{{font:15px -apple-system,BlinkMacSystemFont,sans-serif;margin:0;background:#f5f5f7;color:#1d1d1f}}
main{{max-width:980px;margin:36px auto;padding:0 24px}}h1{{font-size:28px}}.summary{{font-size:44px;font-weight:700}}
.chart{{display:flex;align-items:end;gap:6px;height:230px;padding:22px;background:white;border-radius:12px;overflow-x:auto}}
.day{{min-width:22px;text-align:center;display:flex;flex-direction:column;justify-content:end;height:100%}}.bar{{background:#d9685d;border-radius:4px 4px 1px 1px}}
.day span{{font-size:9px;color:#6e6e73;transform:rotate(-55deg);margin-top:16px}}.day b{{font-size:10px;margin-top:10px}}
.actions{{margin-top:20px;display:flex;gap:12px}}a,button{{font:inherit;padding:9px 14px;border-radius:7px;border:0;background:#0071e3;color:white;text-decoration:none}}
button{{background:#b42318;cursor:pointer}}</style></head><body><main><h1>最近 30 天专注统计</h1>
<div class="summary">{total} 个番茄</div><p>每日完成趋势</p><div class="chart">{bars}</div>
<div class="actions"><a href="/stats.csv">导出 CSV</a><button onclick="clearStats()">删除全部统计</button></div>
<script>async function clearStats(){{if(!confirm('确定删除全部番茄统计？'))return;
await fetch('/clear?token={token}',{{method:'POST'}});location.reload();}}</script></main></body></html>"""


class _StatsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/stats.csv":
            payload = pomodoro_stats_csv(
                self.server.app.pomodoro_stats_snapshot()
            ).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/csv; charset=utf-8")
            self.send_header("Content-Disposition", "attachment; filename=pomodoro-stats.csv")
        else:
            series = pomodoro_stats_last_days(
                self.server.app.pomodoro_stats_snapshot()
            )
            payload = pomodoro_stats_html(series, self.server.token).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        if self.path != f"/clear?token={self.server.token}":
            self.send_error(403)
            return
        if not self.server.app.clear_pomodoro_stats_from_server():
            self.send_error(503)
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, _format, *_args):
        return


def _send_cli_request(request: dict, launch=True) -> dict:
    """Send one request to the local menu-bar instance."""
    def attempt():
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3)
            client.connect(str(CONTROL_SOCKET_PATH))
            client.sendall((json.dumps(request, ensure_ascii=False) + "\n").encode("utf-8"))
            chunks = []
            while True:
                chunk = client.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
            return json.loads(b"".join(chunks).decode("utf-8"))

    try:
        return attempt()
    except (FileNotFoundError, ConnectionRefusedError, socket.timeout, OSError):
        if not launch:
            raise RuntimeError("MultiTimer is not running")
        launched = subprocess.run(
            ["/usr/bin/open", "-b", APP_BUNDLE_ID], check=False, capture_output=True
        )
        if launched.returncode != 0 and not getattr(sys, "frozen", False):
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve())],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                start_new_session=True, close_fds=True,
            )
        for _ in range(30):
            time.sleep(0.1)
            try:
                return attempt()
            except (FileNotFoundError, ConnectionRefusedError, socket.timeout, OSError):
                continue
        raise RuntimeError("Could not connect to the MultiTimer menu bar app")


def _run_cli(argv: list) -> int:
    command = argv[0] if argv else "help"
    if command in {"help", "--help", "-h"}:
        print(
            "Usage:\n"
            "  multitimer start [NAME] MINUTES\n"
            "  multitimer start --stopwatch [NAME]\n"
            "  multitimer list\n"
            "  multitimer pause ID_OR_NAME\n"
            "  multitimer cancel ID_OR_NAME\n"
            "  multitimer pomodoro start|pause|skip|stop|status"
        )
        return 0
    request = {"command": command}
    if command == "pomodoro":
        action = argv[1].lower() if len(argv) > 1 else "status"
        if action not in {"start", "pause", "skip", "stop", "status"}:
            print(f"Unknown pomodoro action: {action}", file=sys.stderr)
            return 2
        request["action"] = action
    elif command == "start":
        args = argv[1:]
        if "--stopwatch" in args:
            args.remove("--stopwatch")
            request.update({"kind": "stopwatch", "name": " ".join(args).strip()})
        else:
            if not args:
                print("start requires MINUTES", file=sys.stderr)
                return 2
            try:
                minutes = float(args[-1])
                if not math.isfinite(minutes) or minutes <= 0:
                    raise ValueError
                seconds = min(MAX_DURATION_SECONDS, int(round(minutes * 60)))
            except (ValueError, OverflowError):
                print("the last start argument must be positive finite MINUTES", file=sys.stderr)
                return 2
            request.update({
                "kind": "countdown",
                "name": " ".join(args[:-1]).strip(),
                "seconds": seconds,
            })
    elif command in {"pause", "cancel"}:
        if len(argv) < 2:
            print(f"{command} requires an ID or name", file=sys.stderr)
            return 2
        request["target"] = " ".join(argv[1:]).strip()
    elif command != "list":
        print(f"Unknown command: {command}", file=sys.stderr)
        return 2
    try:
        response = _send_cli_request(request)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if not response.get("ok"):
        print(response.get("error", "Command failed"), file=sys.stderr)
        return 1
    if command == "pomodoro" and request.get("action") == "status":
        print(response.get("status", "unknown"))
    elif command == "list":
        rows = response.get("timers", [])
        if not rows:
            print("No active timers")
        for item in rows:
            marker = "⏱" if item.get("kind") == "stopwatch" else "◷"
            state = "paused" if item.get("paused") else item.get("time", "")
            print(f"{marker} {item['id'][:8]}  {state:>8}  {item['label']}")
    else:
        print(response.get("message", "OK"))
    return 0


_EDIT_KEY_SELECTORS = {
    "x": "cut:",
    "c": "copy:",
    "v": "paste:",
    "a": "selectAll:",
    "z": "undo:",
}


class _EditableTextField(NSTextField):
    """Text field that resolves ⌘X/⌘C/⌘V/⌘A/⌘Z on its own.

    A menu-bar app has no visible main menu, so AppKit does not route those
    key equivalents to the field editor while a popover field is being edited.
    """

    def performKeyEquivalent_(self, event):
        if event.modifierFlags() & NSEventModifierFlagCommand and self.currentEditor() is not None:
            key = str(event.charactersIgnoringModifiers() or "").lower()
            selector = _EDIT_KEY_SELECTORS.get(key)
            if key == "z" and event.modifierFlags() & NSEventModifierFlagShift:
                selector = "redo:"
            if selector and NSApp.sendAction_to_from_(selector, None, self):
                return True
        return objc.super(_EditableTextField, self).performKeyEquivalent_(event)


class _RenameTextField(_EditableTextField):
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


def _set_inline_editing(field, enabled):
    """Apply the shared native appearance for an inline text editor."""
    field.setEditable_(enabled)
    field.setSelectable_(enabled)
    field.setBezeled_(enabled)
    field.setDrawsBackground_(enabled)
    field.setFocusRingType_(NSFocusRingTypeDefault if enabled else NSFocusRingTypeNone)
    if enabled:
        field.selectText_(None)


def _handle_inline_editor_command(controller, control, command):
    """Handle Escape and Return consistently for inline editors."""
    command_name = command.decode("ascii") if isinstance(command, bytes) else str(command)
    if command_name == "cancelOperation:":
        controller._cancel_requested = True
        control.window().makeFirstResponder_(None)
        return True
    if command_name in {"insertNewline:", "insertLineBreak:"}:
        control.window().makeFirstResponder_(None)
        return True
    return False


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

    def cancel(self):
        """Cancel active renaming before its timer view is removed."""
        if not self._editing:
            return
        self._cancel_requested = True
        window = self._field.window()
        if window is not None:
            window.makeFirstResponder_(None)

    def begin(self):
        if self._editing:
            return
        self._editing = True
        self._cancel_requested = False
        self._original = self._timer["label"]
        _set_inline_editing(self._field, True)

    def _finish(self):
        if not self._editing:
            return
        value = self._original if self._cancel_requested else self._field.stringValue().strip()
        if not value:
            value = self._original
        self._timer["label"] = value
        self._field.setStringValue_(value)
        self._field.setToolTip_(f"{value}\n{self._owner.tr('rename_tip')}")
        _set_inline_editing(self._field, False)
        self._editing = False
        self._cancel_requested = False
        self._owner._persist()

    def controlTextDidEndEditing_(self, _notification):
        self._finish()

    def control_textView_doCommandBySelector_(self, control, _text_view, command):
        return _handle_inline_editor_command(self, control, command)


class _TimeField(_EditableTextField):
    """Time label with independently selectable hour, minute, and second fields."""

    def initWithFrame_(self, frame):
        self = objc.super(_TimeField, self).initWithFrame_(frame)
        if self is None:
            return None
        self._time_controller = None
        return self

    def setTimeController_(self, controller):
        self._time_controller = controller

    def mouseDown_(self, event):
        if self._time_controller is None:
            objc.super(_TimeField, self).mouseDown_(event)
            return
        point = self.convertPoint_fromView_(event.locationInWindow(), None)
        segment = time_segment_for_position(point.x, self.bounds().size.width)
        if not self.isEditable():
            self._time_controller.beginWithSegment_(segment)
            return
        objc.super(_TimeField, self).mouseDown_(event)
        self._time_controller.selectSegment_(segment)


class _TimeEditController(NSObject):
    """Own one inline time editor and commit its text through a callback."""

    def initWithField_commit_(self, field, commit):
        self = objc.super(_TimeEditController, self).init()
        if self is None:
            return None
        self._field = field
        self._commit = commit
        self._editing = False
        self._cancel_requested = False
        self._original = field.stringValue()
        self._segment = 0
        self._digit_index = 0
        self._event_owner = None
        return self

    def editing(self):
        return self._editing

    def cancel(self):
        """Cancel active editing and release the shared AppKit field editor."""
        if not self._editing:
            return
        self._cancel_requested = True
        window = self._field.window()
        if window is not None:
            window.makeFirstResponder_(None)

    def begin(self):
        self.beginWithSegment_(0)

    def beginWithSegment_(self, segment):
        if self._editing:
            self.selectSegment_(segment)
            return
        self._editing = True
        self._cancel_requested = False
        self._original = self._field.stringValue()
        if self._event_owner is not None:
            self._event_owner._active_time_editor = self
        _set_inline_editing(self._field, True)
        self.selectSegment_(segment)

    def setEventOwner_(self, owner):
        self._event_owner = owner

    def selectSegment_(self, segment):
        self._segment = min(2, max(0, int(segment)))
        self._digit_index = 0
        editor = self._field.currentEditor()
        window = self._field.window()
        if editor is not None and window is not None:
            window.makeFirstResponder_(editor)
            location, length = time_segment_range(self._segment)
            editor.setSelectedRange_(NSMakeRange(location, length))

    def insertDigit_(self, digit):
        if not self._editing or digit not in "0123456789":
            return False
        value = replace_time_segment_digit(
            self._field.stringValue(), self._segment, digit, self._digit_index
        )
        self._field.setStringValue_(value)
        self._digit_index = (self._digit_index + 1) % 2
        editor = self._field.currentEditor()
        if editor is not None:
            location, length = time_segment_range(self._segment)
            editor.setSelectedRange_(NSMakeRange(location, length))
        return True

    def _finish(self):
        if not self._editing:
            return
        text = self._field.stringValue()
        self._editing = False
        if self._event_owner is not None and self._event_owner._active_time_editor is self:
            self._event_owner._active_time_editor = None
        cancelled = self._cancel_requested
        self._cancel_requested = False
        _set_inline_editing(self._field, False)
        if cancelled or not self._commit(text):
            self._field.setStringValue_(self._original)

    def controlTextDidEndEditing_(self, _notification):
        self._finish()

    def control_textView_doCommandBySelector_(self, control, _text_view, command):
        return _handle_inline_editor_command(self, control, command)


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
        self._initial_timers = state["timers"]
        self._skipped_update = state["skipped_update"]
        self.settings = state["settings"]
        self.language = _language_for_settings(self.settings)
        self.timers = []          # dict: id/label/start_ts/end_ts/view/name/remaining
        self.pomodoro = {
            "phase": "idle",
            "end_ts": 0.0,
            "paused_at": 0.0,
            "session_id": "",
        }
        self.pomodoro_stats = load_pomodoro_stats()
        self._stats_lock = threading.RLock()
        self._stats_server = None
        self._icloud_store = None
        self._settings_revision = float(self.settings.get("sync_revision") or 0)
        self._retain = []         # 全局 target 保活
        self._closed_at = 0.0
        self._did_finish_launching = False
        self._update_in_progress = False
        self._control_server = None
        self._control_lock = None
        self._control_socket_identity = None
        self._status_signature = None
        self._status_images = {}
        self._default_status_image = None
        self._active_time_editor = None
        self._key_monitor = None
        self._pending_seconds = DEFAULT_DURATION_SECONDS
        return self

    @objc.python_method
    def tr(self, key, **values):
        value = STRINGS[self.language].get(key, STRINGS["en"].get(key, key))
        return value.format(**values) if values else value

    def applicationDidFinishLaunching_(self, _notification):
        """Create the status item only after AppKit has finished launching."""
        if self._did_finish_launching:
            return
        self._did_finish_launching = True
        self._build_main_menu()
        self._build_status_item()
        self._build_popover()
        self._install_time_key_monitor()
        self._setup_icloud_sync()
        self._setup_notifications()
        self._setup_url_scheme()
        self._start_control_server()
        NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
            self, "systemColorsDidChange:", NSSystemColorsDidChangeNotification, None
        )
        for t in self._initial_timers:
            self._add_timer_row(t)
        self._initial_timers = []
        self._update_size()
        self._start_ticker()
        AppHelper.callLater(1.5, self._verify_status_item)
        if os.environ.get("MULTITIMER_PREVIEW") == "1":
            self._show_preview_window()
        else:
            # The network work happens on a background thread. A startup check
            # stays quiet when there is no update or the network is unavailable.
            self._check_for_updates(automatic=True)

    def _install_time_key_monitor(self):
        def handle(event):
            editor = self._active_time_editor
            modifiers = event.modifierFlags()
            if editor is None or modifiers & NSEventModifierFlagCommand:
                return event
            characters = str(event.charactersIgnoringModifiers() or "")
            if len(characters) == 1 and editor.insertDigit_(characters):
                return None
            return event

        self._key_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
            NSEventMaskKeyDown, handle
        )

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
        wants_summary = self.settings.get("show_remaining") or self.settings.get("show_count")
        initial_length = NSVariableStatusItemLength if wants_summary else NSSquareStatusItemLength
        self.status_item = bar.statusItemWithLength_(initial_length)
        self._status_signature = None
        if self.status_item.respondsToSelector_("setAutosaveName:"):
            self.status_item.setAutosaveName_(_status_item_autosave_name())
        if self.status_item.respondsToSelector_("setBehavior:"):
            # This app has no Dock icon or separate window. If the user removes
            # its only entry point, quitting is safer than leaving an invisible
            # background process behind.
            self.status_item.setBehavior_(NSStatusItemBehaviorTerminationOnRemoval)
        btn = self.status_item.button()
        btn.setToolTip_(APP_NAME)
        btn.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(12, NSFontWeightMedium))
        img = NSImage.imageWithSystemSymbolName_accessibilityDescription_("timer", APP_NAME)
        if img is None:
            img = NSImage.imageNamed_(NSImageNameStatusAvailable)
        if img is not None:
            img.setTemplate_(True)
            self._default_status_image = img
            btn.setImage_(img)
            btn.setImagePosition_(NSImageOnly)
        else:
            btn.setTitle_("⏱")
        toggle = _Action.alloc().initWithCallback_(lambda s: self._toggle_popover())
        self._retain.append(toggle)
        btn.setTarget_(toggle)
        btn.setAction_("invoke:")
        if self.status_item.respondsToSelector_("setVisible:"):
            self.status_item.setVisible_(True)
        self._refresh_status_item()

    def _pomodoro_status_image(self, phase):
        cached = self._status_images.get(phase)
        if cached is not None:
            return cached
        color = (
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.85, 0.41, 0.36, 1.0)
            if phase == "work"
            else NSColor.colorWithSRGBRed_green_blue_alpha_(0.41, 0.66, 0.46, 1.0)
        )
        image = NSImage.alloc().initWithSize_(NSMakeSize(18, 18))
        image.lockFocus()
        color.setFill()
        background = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(1, 2, 16, 14), 4, 4
        )
        background.fill()
        symbol_color = NSColor.labelColor().colorWithAlphaComponent_(0.92)
        symbol_color.setStroke()
        ring = NSBezierPath.bezierPathWithOvalInRect_(NSMakeRect(5, 5, 8, 8))
        ring.setLineWidth_(1.5)
        ring.stroke()
        hand = NSBezierPath.bezierPath()
        hand.moveToPoint_((9, 9))
        hand.lineToPoint_((9, 6.5))
        hand.lineToPoint_((11, 9))
        hand.setLineWidth_(1.25)
        hand.stroke()
        image.unlockFocus()
        image.setTemplate_(False)
        self._status_images[phase] = image
        return image

    def _restore_default_status_image(self):
        button = self.status_item.button()
        if self._default_status_image is not None and button.image() is not self._default_status_image:
            button.setImage_(self._default_status_image)

    def _refresh_status_item(self):
        if not getattr(self, "status_item", None):
            return
        active = [t for t in self.timers if not t.get("finished")]
        pomodoro_phase = self.pomodoro.get("phase")
        if pomodoro_phase in {"work", "break"}:
            title = fmt_pomodoro_remaining(pomodoro_remaining(self.pomodoro))
            signature = (title, pomodoro_phase, bool(self.pomodoro.get("paused_at")))
            if signature == self._status_signature:
                return
            button = self.status_item.button()
            button.setTitle_(title)
            button.setImage_(self._pomodoro_status_image(pomodoro_phase))
            button.setImagePosition_(NSImageLeft)
            self.status_item.setLength_(NSVariableStatusItemLength)
            self._status_signature = signature
            return
        parts = []
        if self.settings.get("show_remaining") and active:
            countdowns = [t for t in active if t.get("kind", "countdown") == "countdown"]
            if countdowns:
                nearest = min(countdowns, key=timer_remaining)
                parts.append(fmt_status_remaining(timer_remaining(nearest)))
        if self.settings.get("show_count"):
            parts.append(str(len(active)))
        title = " · ".join(parts)
        signature = (title, "default", bool(title))
        if signature == self._status_signature:
            return
        self._restore_default_status_image()
        button = self.status_item.button()
        button.setTitle_(title)
        button.setImagePosition_(NSImageLeft if title else NSImageOnly)
        self.status_item.setLength_(NSVariableStatusItemLength if title else NSSquareStatusItemLength)
        self._status_signature = signature

    def _verify_status_item(self):
        item = getattr(self, "status_item", None)
        if item is None:
            return
        # Control Center may finish applying its saved placement after AppKit
        # creates the item. Reassert visibility once after that restoration.
        if item.respondsToSelector_("setVisible:"):
            item.setVisible_(True)
        visible = True
        if item.respondsToSelector_("isVisible"):
            visible = bool(item.isVisible())
        if visible:
            return
        if item.respondsToSelector_("setVisible:"):
            item.setVisible_(True)
        AppHelper.callLater(0.8, self._status_item_recheck)

    def _status_item_recheck(self):
        item = getattr(self, "status_item", None)
        if item is not None and (not item.respondsToSelector_("isVisible") or item.isVisible()):
            return
        response = self._show_alert(
            self.tr("status_hidden"), self.tr("status_hidden_detail"),
            (self.tr("retry"), self.tr("open_settings"), self.tr("later")),
        )
        if response == 1000:
            NSStatusBar.systemStatusBar().removeStatusItem_(self.status_item)
            self._build_status_item()
        elif response == 1001:
            self._open_url("x-apple.systempreferences:com.apple.ControlCenter-Settings.extension")

    def _setup_url_scheme(self):
        manager = NSAppleEventManager.sharedAppleEventManager()
        manager.setEventHandler_andSelector_forEventClass_andEventID_(
            self, "handleGetURLEvent:withReplyEvent:",
            int.from_bytes(b"GURL", "big"), int.from_bytes(b"GURL", "big"),
        )

    def handleGetURLEvent_withReplyEvent_(self, event, _reply):
        descriptor = event.paramDescriptorForKeyword_(int.from_bytes(b"----", "big"))
        try:
            request = _parse_multitimer_url(descriptor.stringValue())
            self._execute_control_request(request)
        except Exception as exc:
            self._show_alert("MultiTimer URL", str(exc))

    def _start_control_server(self):
        try:
            STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
            lock_stream = CONTROL_LOCK_PATH.open("a+")
            try:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                lock_stream.close()
                self._control_server = None
                return
            self._control_lock = lock_stream
            if CONTROL_SOCKET_PATH.exists():
                try:
                    _send_cli_request({"command": "list"}, launch=False)
                except RuntimeError:
                    CONTROL_SOCKET_PATH.unlink()
                else:
                    lock_stream.close()
                    self._control_lock = None
                    self._control_server = None
                    return
            server = _ControlServer(str(CONTROL_SOCKET_PATH), _ControlHandler)
            server.app = self
            os.chmod(CONTROL_SOCKET_PATH, 0o600)
            socket_stat = CONTROL_SOCKET_PATH.stat()
            self._control_lock = lock_stream
            self._control_socket_identity = (socket_stat.st_dev, socket_stat.st_ino)
            self._control_server = server
            threading.Thread(target=server.serve_forever, daemon=True).start()
        except (OSError, RuntimeError):
            self._control_server = None
            if getattr(self, "_control_lock", None) is not None:
                self._control_lock.close()
                self._control_lock = None

    def handle_cli_request(self, request):
        result = {}
        ready = threading.Event()

        def execute():
            try:
                result.update(self._execute_control_request(request))
            except Exception as exc:
                result.update({"ok": False, "error": str(exc)})
            finally:
                ready.set()

        AppHelper.callAfter(execute)
        if not ready.wait(5):
            return {"ok": False, "error": "MultiTimer did not respond in time"}
        return result

    def _find_timer(self, target):
        target = str(target or "").strip().lower()
        matches = [
            timer for timer in self.timers
            if timer.get("id", "").lower().startswith(target) or timer.get("label", "").lower() == target
        ]
        if len(matches) != 1:
            raise ValueError("Timer not found or name is ambiguous")
        return matches[0]

    def _execute_control_request(self, request):
        command = str(request.get("command", ""))
        if command == "start":
            label = str(request.get("name") or "").strip() or None
            if request.get("kind") == "stopwatch":
                timer = self._start_stopwatch(label)
            else:
                try:
                    seconds = int(request.get("seconds") or 0)
                except (TypeError, ValueError, OverflowError) as exc:
                    raise ValueError("Duration must be a positive finite number") from exc
                if not 0 < seconds <= MAX_DURATION_SECONDS:
                    raise ValueError("Duration must be between 1 second and 24 hours")
                timer = self._start_timer(seconds, label)
            return {"ok": True, "message": f"Started {timer['label']}", "id": timer["id"]}
        if command == "pomodoro":
            action = str(request.get("action") or "status").lower()
            phase = self.pomodoro.get("phase", "idle")
            active = phase in {"work", "break"}
            if action == "start":
                if phase not in {"idle", "ready"}:
                    raise ValueError("Pomodoro is already active")
                self._start_pomodoro_work()
            elif action == "pause":
                if not active:
                    raise ValueError("Pomodoro is not active")
                self._toggle_pomodoro_pause()
            elif action == "skip":
                if not active:
                    raise ValueError("Pomodoro is not active")
                self._skip_pomodoro_phase()
            elif action == "stop":
                if not active:
                    raise ValueError("Pomodoro is not active")
                self._stop_pomodoro()
            elif action != "status":
                raise ValueError("Unsupported Pomodoro action")
            phase = self.pomodoro.get("phase", "idle")
            remaining = fmt_pomodoro_remaining(pomodoro_remaining(self.pomodoro))
            paused = bool(self.pomodoro.get("paused_at"))
            status = f"{phase} {'paused' if paused else remaining}"
            return {
                "ok": True,
                "message": f"Pomodoro {action}: {status}",
                "status": status,
                "phase": phase,
                "paused": paused,
                "remaining": remaining,
                "completed_today": self._today_pomodoro_count(),
            }
        if command == "list":
            rows = []
            for timer in self.timers:
                rows.append({
                    "id": timer["id"], "label": timer["label"], "kind": timer.get("kind", "countdown"),
                    "paused": timer_is_paused(timer), "time": fmt_remaining(timer_display_seconds(timer)),
                })
            return {"ok": True, "timers": rows}
        if command in {"pause", "cancel"}:
            timer = self._find_timer(request.get("target"))
            if command == "pause":
                self._toggle_pause(timer)
                return {"ok": True, "message": f"Toggled pause for {timer['label']}"}
            self._cancel_timer(timer)
            return {"ok": True, "message": f"Cancelled {timer['label']}"}
        raise ValueError("Unsupported command")

    # -- 关于 / 更新 -------------------------------------------------------
    def _app_icon(self):
        return NSImage.alloc().initWithContentsOfFile_(str(resource_path("assets/app-icon.png")))

    def _show_alert(self, title, detail="", buttons=("OK",)):
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

    def _login_service(self):
        try:
            bundle = NSBundle.bundleWithPath_("/System/Library/Frameworks/ServiceManagement.framework")
            bundle.load()
            return objc.lookUpClass("SMAppService").mainAppService()
        except Exception:
            return None

    def _show_settings(self):
        if not getattr(self, "_settings_vc", None):
            self._build_settings_view()
        self._refresh_settings_controls()
        self.popover.setContentViewController_(self._settings_vc)
        self._fit_popover_to(self._settings_content_view)

    def _build_settings_view(self):
        content = NSView.alloc().initWithFrame_(NSMakeRect(0, 0, PANEL_WIDTH + 20, 190))
        root = _vstack(8)
        root.setTranslatesAutoresizingMaskIntoConstraints_(False)
        content.addSubview_(root)
        root.leadingAnchor().constraintEqualToAnchor_constant_(content.leadingAnchor(), 10).setActive_(True)
        root.trailingAnchor().constraintEqualToAnchor_constant_(content.trailingAnchor(), -10).setActive_(True)
        root.topAnchor().constraintEqualToAnchor_constant_(content.topAnchor(), 9).setActive_(True)
        root.bottomAnchor().constraintEqualToAnchor_constant_(content.bottomAnchor(), -9).setActive_(True)
        root.widthAnchor().constraintEqualToConstant_(PANEL_WIDTH).setActive_(True)

        header = _hstack(6)
        back = _button("‹", lambda s: self._show_main_view(), self._retain, small=True, quiet=True)
        back.setToolTip_(self.tr("back"))
        back.widthAnchor().constraintEqualToConstant_(28).setActive_(True)
        header.addArrangedSubview_(back)
        title = NSTextField.labelWithString_(self.tr("settings_title"))
        title.setFont_(NSFont.systemFontOfSize_weight_(13.5, NSFontWeightSemibold))
        header.addArrangedSubview_(title)
        header_spacer = NSView.alloc().init()
        header.addArrangedSubview_(header_spacer)
        header_spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        root.addArrangedSubview_(header)
        header.leadingAnchor().constraintEqualToAnchor_(root.leadingAnchor()).setActive_(True)
        header.trailingAnchor().constraintEqualToAnchor_(root.trailingAnchor()).setActive_(True)

        separator = NSBox.alloc().init()
        separator.setBoxType_(NSBoxSeparator)
        root.addArrangedSubview_(separator)
        separator.leadingAnchor().constraintEqualToAnchor_(root.leadingAnchor()).setActive_(True)
        separator.trailingAnchor().constraintEqualToAnchor_(root.trailingAnchor()).setActive_(True)

        self._setting_controls = {}

        def add_switch(key, title, callback):
            control = NSButton.alloc().init()
            control.setButtonType_(NSSwitchButton)
            control.setTitle_(title)
            control.setFont_(NSFont.systemFontOfSize_(12))
            action = _Action.alloc().initWithCallback_(callback)
            self._retain.append(action)
            control.setTarget_(action)
            control.setAction_("invoke:")
            root.addArrangedSubview_(control)
            control.leadingAnchor().constraintEqualToAnchor_(root.leadingAnchor()).setActive_(True)
            control.trailingAnchor().constraintEqualToAnchor_(root.trailingAnchor()).setActive_(True)
            self._setting_controls[key] = control

        add_switch("launch_at_login", self.tr("launch_at_login"), self._login_setting_changed)
        add_switch(
            "show_remaining", self.tr("show_remaining"),
            lambda sender: self._boolean_setting_changed("show_remaining", sender),
        )
        add_switch(
            "show_count", self.tr("show_count"),
            lambda sender: self._boolean_setting_changed("show_count", sender),
        )
        add_switch(
            "sort_by_expiry", self.tr("sort_by_expiry"),
            lambda sender: self._boolean_setting_changed("sort_by_expiry", sender),
        )
        add_switch(
            "show_pomodoro", self.tr("show_pomodoro"),
            lambda sender: self._boolean_setting_changed("show_pomodoro", sender),
        )

        pomodoro_label = _section_label(self.tr("pomodoro"))
        root.addArrangedSubview_(pomodoro_label)
        pomodoro_card = _CardView.alloc().init()
        pomodoro_settings = _vstack(5)
        self.pomodoro_work_field, work_editor = self._make_segmented_time_field(
            fmt_remaining(self.settings["pomodoro_work_seconds"]),
            72,
            lambda text: self._pomodoro_duration_changed("pomodoro_work_seconds", text),
        )
        self.pomodoro_break_field, break_editor = self._make_segmented_time_field(
            fmt_remaining(self.settings["pomodoro_break_seconds"]),
            72,
            lambda text: self._pomodoro_duration_changed("pomodoro_break_seconds", text),
        )
        self._retain.extend((work_editor, break_editor))
        for title_key, field in (
            ("pomodoro_work_duration", self.pomodoro_work_field),
            ("pomodoro_break_duration", self.pomodoro_break_field),
        ):
            row = _hstack(6)
            label = NSTextField.labelWithString_(self.tr(title_key))
            label.setFont_(NSFont.systemFontOfSize_(11.5))
            row.addArrangedSubview_(label)
            field_spacer = NSView.alloc().init()
            row.addArrangedSubview_(field_spacer)
            field_spacer.setContentHuggingPriority_forOrientation_(
                1, NSLayoutConstraintOrientationHorizontal
            )
            row.addArrangedSubview_(field)
            pomodoro_settings.addArrangedSubview_(row)
        self.pomodoro_auto_switch = NSButton.alloc().init()
        self.pomodoro_auto_switch.setButtonType_(NSSwitchButton)
        self.pomodoro_auto_switch.setTitle_(self.tr("pomodoro_auto_cycle"))
        self.pomodoro_auto_switch.setFont_(NSFont.systemFontOfSize_(11.5))
        auto_action = _Action.alloc().initWithCallback_(
            lambda sender: self._boolean_setting_changed("pomodoro_auto_cycle", sender)
        )
        self._retain.append(auto_action)
        self.pomodoro_auto_switch.setTarget_(auto_action)
        self.pomodoro_auto_switch.setAction_("invoke:")
        pomodoro_settings.addArrangedSubview_(self.pomodoro_auto_switch)
        _embed_with_insets(pomodoro_card, pomodoro_settings, top=7, right=8, bottom=7, left=8)
        root.addArrangedSubview_(pomodoro_card)
        pomodoro_card.leadingAnchor().constraintEqualToAnchor_(root.leadingAnchor()).setActive_(True)
        pomodoro_card.trailingAnchor().constraintEqualToAnchor_(root.trailingAnchor()).setActive_(True)

        language_card = _CardView.alloc().init()
        language_row = _hstack(6)
        language_text = _vstack(1)
        language_title = NSTextField.labelWithString_(self.tr("language"))
        language_title.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightMedium))
        language_detail = NSTextField.wrappingLabelWithString_(self.tr("language_detail"))
        language_detail.setFont_(NSFont.systemFontOfSize_(10))
        language_detail.setTextColor_(NSColor.secondaryLabelColor())
        language_text.addArrangedSubview_(language_title)
        language_text.addArrangedSubview_(language_detail)
        language_row.addArrangedSubview_(language_text)
        language_spacer = NSView.alloc().init()
        language_row.addArrangedSubview_(language_spacer)
        language_spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        language_button = _button(
            self.tr("open_language_settings"), lambda s: self._open_language_settings(),
            self._retain, small=True,
        )
        language_row.addArrangedSubview_(language_button)
        _embed_with_insets(language_card, language_row, top=6, right=7, bottom=6, left=8)
        root.addArrangedSubview_(language_card)
        language_card.leadingAnchor().constraintEqualToAnchor_(root.leadingAnchor()).setActive_(True)
        language_card.trailingAnchor().constraintEqualToAnchor_(root.trailingAnchor()).setActive_(True)

        vc = NSViewController.alloc().init()
        vc.setView_(content)
        self._settings_content_view = content
        self._settings_vc = vc

    def _refresh_settings_controls(self):
        controls = self._setting_controls
        service = self._login_service()
        login_enabled = bool(service is not None and int(service.status()) == 1)
        controls["launch_at_login"].setState_(
            NSControlStateValueOn if login_enabled else NSControlStateValueOff
        )
        for key in ("show_remaining", "show_count", "sort_by_expiry", "show_pomodoro"):
            controls[key].setState_(
                NSControlStateValueOn if self.settings.get(key) else NSControlStateValueOff
            )
        self.pomodoro_work_field.setStringValue_(
            fmt_remaining(self.settings["pomodoro_work_seconds"])
        )
        self.pomodoro_break_field.setStringValue_(
            fmt_remaining(self.settings["pomodoro_break_seconds"])
        )
        self.pomodoro_auto_switch.setState_(
            NSControlStateValueOn
            if self.settings.get("pomodoro_auto_cycle")
            else NSControlStateValueOff
        )

    def _pomodoro_duration_changed(self, key, text):
        try:
            seconds = parse_duration_text(text)
        except ValueError:
            return False
        if seconds <= 0 or seconds > POMODORO_MAX_SECONDS:
            return False
        self.settings[key] = seconds
        self._settings_revision = time.time()
        self.settings["sync_revision"] = self._settings_revision
        self._persist()
        self._update_pomodoro_view()
        return True

    def _boolean_setting_changed(self, key, sender):
        self.settings[key] = sender.state() == NSControlStateValueOn
        self._settings_revision = time.time()
        self.settings["sync_revision"] = self._settings_revision
        self._persist()
        if key == "sort_by_expiry":
            self._sort_timer_views()
        elif key == "show_pomodoro":
            self.pomodoro_card.setHidden_(not self.settings[key])
            self._update_size()
        else:
            self._refresh_status_item()

    def _login_setting_changed(self, sender):
        desired = sender.state() == NSControlStateValueOn
        service = self._login_service()
        if service is None:
            sender.setState_(NSControlStateValueOff)
            self._show_alert(self.tr("launch_at_login"), "SMAppService is unavailable.")
            return
        try:
            result = service.registerAndReturnError_(None) if desired else service.unregisterAndReturnError_(None)
            ok, error = result if isinstance(result, tuple) else (bool(result), None)
            if not ok:
                raise RuntimeError(str(error or "macOS rejected the login item change"))
        except Exception as exc:
            sender.setState_(NSControlStateValueOff if desired else NSControlStateValueOn)
            self._show_alert(self.tr("launch_at_login"), str(exc))

    def _open_language_settings(self):
        self._open_url("x-apple.systempreferences:com.apple.Localization-Settings.extension")

    def _show_main_view(self):
        self.popover.setContentViewController_(self._vc)
        self._fit_popover_to(self.content_view)

    def _show_about(self):
        if self.popover.isShown():
            self.popover.close()
        source = {
            "homebrew": "Homebrew",
            "dmg": "DMG",
            "development": self.tr("development"),
        }.get(_installation_source_hint(), self.tr("unknown"))
        detail = (
            f"{self.tr('version', version=APP_VERSION)}\n"
            f"{self.tr('source', source=source)}\n\n"
            f"{self.tr('tagline')}\n\n"
            f"{APP_COPYRIGHT}\n"
            f"{self.tr('privacy')}"
        )
        response = self._show_alert(
            self.tr("about"),
            detail,
            (self.tr("check_updates"), self.tr("homepage"), self.tr("close")),
        )
        if response == 1000:
            self._check_for_updates()
        elif response == 1001:
            self._open_url(APP_REPOSITORY)

    def _check_for_updates(self, automatic=False):
        if self._update_in_progress:
            if not automatic:
                self._show_alert(self.tr("update_busy"), self.tr("update_busy_detail"))
            return
        self._update_in_progress = True
        self.status_item.button().setToolTip_(self.tr("checking"))
        threading.Thread(target=self._check_update_worker, args=(automatic,), daemon=True).start()

    def _check_update_worker(self, automatic):
        try:
            release = _fetch_latest_release()
            source = _installation_source()
        except Exception as exc:
            if automatic:
                AppHelper.callAfter(self._automatic_check_failed)
            else:
                AppHelper.callAfter(self._update_failed, f"{self.tr('check_failed')}\n{exc}")
            return
        AppHelper.callAfter(self._present_update, release, source, automatic)

    def _present_update(self, release, source, automatic=False):
        latest = _release_version(release)
        if not latest:
            if automatic:
                self._automatic_check_failed()
            else:
                self._update_failed("GitHub Release 没有有效的版本号")
            return
        if _version_tuple(latest) <= _version_tuple(APP_VERSION):
            self._update_in_progress = False
            self.status_item.button().setToolTip_(APP_NAME)
            if not automatic:
                self._show_alert(self.tr("latest"), self.tr("latest_detail", version=APP_VERSION))
            return

        if automatic and latest == self._skipped_update:
            self._update_in_progress = False
            self.status_item.button().setToolTip_(APP_NAME)
            return

        notes = str(release.get("body") or "该版本包含功能改进与问题修复。").strip()
        if len(notes) > 1100:
            notes = notes[:1097] + "…"
        update_detail = f"{self.tr('current_version', version=APP_VERSION)}\n\n{self.tr('whats_new')}\n{notes}"
        if source == "homebrew":
            brew = _find_brew() or "brew"
            update_detail += (
                f"\n\n{self.tr('brew_will_run')}\n"
                f"{brew} upgrade --cask --no-quit echoforger/multi-timer/multi-timer"
            )
        response = self._show_alert(
            self.tr("found_update", version=latest),
            update_detail,
            (self.tr("update_now"), self.tr("later"), self.tr("skip_version")),
        )
        if response == 1002:
            self._skipped_update = latest
            self._persist()
        if response != 1000:
            self._update_in_progress = False
            self.status_item.button().setToolTip_(APP_NAME)
            return

        if source == "homebrew":
            self.status_item.button().setToolTip_(f"正在通过 Homebrew 更新到 {latest}…")
            threading.Thread(target=self._brew_update_worker, args=(latest,), daemon=True).start()
            return
        if source == "dmg":
            self.status_item.button().setToolTip_(f"正在安装 MultiTimer {latest}…")
            threading.Thread(
                target=self._dmg_update_worker,
                args=(release, latest),
                daemon=True,
            ).start()
            return

        self._update_in_progress = False
        self.status_item.button().setToolTip_(APP_NAME)
        self._open_url(str(release.get("html_url") or f"{APP_REPOSITORY}/releases/latest"))

    def _automatic_check_failed(self):
        """Keep launch-time connectivity failures unobtrusive."""
        self._update_in_progress = False
        self.status_item.button().setToolTip_(APP_NAME)

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
        response = self._show_alert(self.tr("update_failed"), detail, ("OK", self.tr("release_page")))
        if response == 1001:
            self._open_url(f"{APP_REPOSITORY}/releases/latest")

    def _update_succeeded(self, latest, source):
        self._update_in_progress = False
        self.status_item.button().setToolTip_(APP_NAME)
        response = self._show_alert(
            self.tr("update_installed"),
            self.tr("update_installed_detail", version=latest, source=source),
            (self.tr("restart_now"), self.tr("later")),
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
        about_btn.setToolTip_(self.tr("about"))
        header.addArrangedSubview_(about_btn)
        settings_btn = _button("⚙", lambda s: self._show_settings(), self._retain, small=True, quiet=True)
        settings_btn.setToolTip_(self.tr("settings"))
        header.addArrangedSubview_(settings_btn)
        quit_btn = _button("×", lambda s: self._quit(), self._retain, small=True, quiet=True)
        quit_btn.setToolTip_(self.tr("quit"))
        header.addArrangedSubview_(quit_btn)
        root.addArrangedSubview_(header)
        self._fill_width(header)

        # 新建计时器
        self.input_field = _EditableTextField.alloc().initWithFrame_(
            NSMakeRect(0, 0, PANEL_WIDTH, 25)
        )
        self.input_field.setPlaceholderString_(self.tr("timer_name"))
        self.input_field.setFont_(NSFont.systemFontOfSize_(12))
        self.input_field.heightAnchor().constraintEqualToConstant_(25).setActive_(True)
        root.addArrangedSubview_(self.input_field)
        self._fill_width(self.input_field)

        # 时长拉杆 (0 - 24h) + 目标时间
        composer_card = _CardView.alloc().init()
        composer = _vstack(6)

        duration_row = _hstack(7)
        duration_label = NSTextField.labelWithString_(self.tr("duration"))
        duration_label.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightMedium))
        duration_row.addArrangedSubview_(duration_label)
        self.duration_slider = NSSlider.alloc().init()
        self.duration_slider.setMinValue_(0.0)
        self.duration_slider.setMaxValue_(1.0)
        self.duration_slider.setDoubleValue_(
            slider_position_for_seconds(self._pending_seconds)
        )
        self.duration_slider.setControlSize_(NSControlSizeSmall)
        slider_action = _Action.alloc().initWithCallback_(lambda sender: self._slider_changed(sender))
        self._retain.append(slider_action)
        self.duration_slider.setTarget_(slider_action)
        self.duration_slider.setAction_("invoke:")
        self.duration_slider.setContinuous_(True)
        duration_row.addArrangedSubview_(self.duration_slider)
        self.duration_field, duration_editor = self._make_segmented_time_field(
            fmt_remaining(self._pending_seconds),
            72,
            lambda text: self._duration_text_changed(text),
        )
        self._retain.append(duration_editor)
        duration_row.addArrangedSubview_(self.duration_field)
        composer.addArrangedSubview_(duration_row)

        target_row = _hstack(7)
        target_label = NSTextField.labelWithString_(self.tr("target_time"))
        target_label.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightMedium))
        target_row.addArrangedSubview_(target_label)
        self.target_field, target_editor = self._make_segmented_time_field(
            fmt_clock_time(time.time() + self._pending_seconds),
            72,
            lambda text: self._target_text_changed(text),
        )
        self._retain.append(target_editor)
        target_row.addArrangedSubview_(self.target_field)
        target_spacer = NSView.alloc().init()
        target_row.addArrangedSubview_(target_spacer)
        target_spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        stopwatch_btn = _button(self.tr("stopwatch"), lambda s: self._start_stopwatch(), self._retain, small=True)
        target_row.addArrangedSubview_(stopwatch_btn)
        start_btn = _button(self.tr("start"), lambda s: self._start_pending(), self._retain, accent=True, small=True)
        target_row.addArrangedSubview_(start_btn)
        composer.addArrangedSubview_(target_row)

        _embed_with_insets(composer_card, composer, top=7, right=8, bottom=7, left=9)
        root.addArrangedSubview_(composer_card)
        self._fill_width(composer_card)
        duration_row.leadingAnchor().constraintEqualToAnchor_(composer.leadingAnchor()).setActive_(True)
        duration_row.trailingAnchor().constraintEqualToAnchor_(composer.trailingAnchor()).setActive_(True)
        target_row.leadingAnchor().constraintEqualToAnchor_(composer.leadingAnchor()).setActive_(True)
        target_row.trailingAnchor().constraintEqualToAnchor_(composer.trailingAnchor()).setActive_(True)

        self._build_pomodoro_card(root)

        # 进行中标题 + 列表
        # Notification permission guidance stays compact and appears only when needed.
        self.notification_warning = _hstack(5)
        warning_text = NSTextField.wrappingLabelWithString_(self.tr("notification_denied"))
        warning_text.setFont_(NSFont.systemFontOfSize_(10.5))
        warning_text.setTextColor_(NSColor.secondaryLabelColor())
        self.notification_warning.addArrangedSubview_(warning_text)
        warning_spacer = NSView.alloc().init()
        self.notification_warning.addArrangedSubview_(warning_spacer)
        warning_spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        self.notification_settings_button = _button(
            self.tr("open_settings"), lambda s: self._open_notification_settings(), self._retain, small=True
        )
        self.notification_warning.addArrangedSubview_(self.notification_settings_button)
        self.notification_warning.setHidden_(True)
        root.addArrangedSubview_(self.notification_warning)
        self._fill_width(self.notification_warning)

        self.section_label = _section_label(self.tr("empty"))
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

    def _build_pomodoro_card(self, root):
        card = _CardView.alloc().init()
        stack = _vstack(5)
        header = _hstack(5)
        title = NSTextField.labelWithString_(self.tr("pomodoro"))
        title.setFont_(NSFont.systemFontOfSize_weight_(12, NSFontWeightSemibold))
        header.addArrangedSubview_(title)
        spacer = NSView.alloc().init()
        header.addArrangedSubview_(spacer)
        spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        self.pomodoro_phase_label = _section_label(self.tr("pomodoro_ready"))
        header.addArrangedSubview_(self.pomodoro_phase_label)
        stack.addArrangedSubview_(header)

        self.pomodoro_today_label = _section_label(
            self.tr("pomodoro_today", count=self._today_pomodoro_count())
        )
        stack.addArrangedSubview_(self.pomodoro_today_label)

        self.pomodoro_time_label = NSTextField.labelWithString_(
            fmt_pomodoro_remaining(self.settings["pomodoro_work_seconds"])
        )
        self.pomodoro_time_label.setFont_(
            NSFont.monospacedDigitSystemFontOfSize_weight_(20, NSFontWeightSemibold)
        )
        self.pomodoro_time_label.setTextColor_(NSColor.controlAccentColor())
        stack.addArrangedSubview_(self.pomodoro_time_label)

        actions = _hstack(4)
        self.pomodoro_main_button = _button(
            self.tr("pomodoro_start"), lambda sender: self._pomodoro_main_action(),
            self._retain, accent=True, small=True,
        )
        self.pomodoro_skip_button = _button(
            self.tr("pomodoro_skip"), lambda sender: self._skip_pomodoro_phase(),
            self._retain, small=True,
        )
        self.pomodoro_stop_button = _button(
            self.tr("pomodoro_stop"), lambda sender: self._stop_pomodoro(),
            self._retain, small=True, quiet=True,
        )
        self.pomodoro_stats_button = _button(
            "▥", lambda sender: self._open_pomodoro_stats(),
            self._retain, small=True, quiet=True,
        )
        self.pomodoro_stats_button.setToolTip_(self.tr("pomodoro_stats"))
        actions.addArrangedSubview_(self.pomodoro_main_button)
        actions.addArrangedSubview_(self.pomodoro_skip_button)
        actions.addArrangedSubview_(self.pomodoro_stats_button)
        action_spacer = NSView.alloc().init()
        actions.addArrangedSubview_(action_spacer)
        action_spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        actions.addArrangedSubview_(self.pomodoro_stop_button)
        stack.addArrangedSubview_(actions)

        _embed_with_insets(card, stack, top=7, right=8, bottom=7, left=8)
        root.addArrangedSubview_(card)
        self._fill_width(card)
        for row in (header, actions):
            row.leadingAnchor().constraintEqualToAnchor_(stack.leadingAnchor()).setActive_(True)
            row.trailingAnchor().constraintEqualToAnchor_(stack.trailingAnchor()).setActive_(True)
        self.pomodoro_card = card
        card.setHidden_(not self.settings.get("show_pomodoro", True))
        self._update_pomodoro_view()

    def _fill_width(self, view):
        view.leadingAnchor().constraintEqualToAnchor_(self.root_stack.leadingAnchor()).setActive_(True)
        view.trailingAnchor().constraintEqualToAnchor_(self.root_stack.trailingAnchor()).setActive_(True)

    # -- 番茄钟 -------------------------------------------------------------
    def _today_pomodoro_count(self):
        with self._stats_lock:
            return int(
                self.pomodoro_stats.get(datetime.date.today().isoformat(), 0)
            )

    def pomodoro_stats_snapshot(self):
        with self._stats_lock:
            return dict(self.pomodoro_stats)

    def _open_pomodoro_stats(self):
        if self._stats_server is None:
            server = ThreadingHTTPServer(("127.0.0.1", 0), _StatsHandler)
            server.app = self
            server.token = uuid.uuid4().hex
            self._stats_server = server
            threading.Thread(target=server.serve_forever, daemon=True).start()
        port = self._stats_server.server_address[1]
        webbrowser.open(f"http://127.0.0.1:{port}/")

    def clear_pomodoro_stats_from_server(self):
        finished = threading.Event()

        def clear():
            try:
                self._clear_pomodoro_stats()
            finally:
                finished.set()

        AppHelper.callAfter(clear)
        return finished.wait(5)

    def _clear_pomodoro_stats(self):
        with self._stats_lock:
            self.pomodoro_stats = {}
            save_pomodoro_stats(self.pomodoro_stats)
        self._sync_to_icloud()
        self._update_pomodoro_view()


    def _record_completed_pomodoro(self, completed_at):
        day = datetime.datetime.fromtimestamp(completed_at).date().isoformat()
        with self._stats_lock:
            self.pomodoro_stats[day] = int(self.pomodoro_stats.get(day, 0)) + 1
            save_pomodoro_stats(self.pomodoro_stats)
        self._sync_to_icloud()

    def _pomodoro_main_action(self):
        phase = self.pomodoro.get("phase")
        if phase in {"idle", "ready"}:
            self._start_pomodoro_work()
            return
        self._toggle_pomodoro_pause()

    def _start_pomodoro_phase(self, phase):
        duration_key = (
            "pomodoro_work_seconds" if phase == "work" else "pomodoro_break_seconds"
        )
        duration = max(1, int(self.settings.get(duration_key) or 1))
        self.pomodoro.update({
            "phase": phase,
            "end_ts": time.time() + duration,
            "paused_at": 0.0,
            "session_id": uuid.uuid4().hex,
        })
        self._update_pomodoro_view()
        self._refresh_status_item()
        self._update_size()

    def _start_pomodoro_work(self):
        self._start_pomodoro_phase("work")

    def _start_pomodoro_break(self):
        self._start_pomodoro_phase("break")

    def _skip_pomodoro_phase(self):
        phase = self.pomodoro.get("phase")
        if phase == "work":
            self._start_pomodoro_break()
        elif phase == "break":
            self._start_pomodoro_work()

    def _toggle_pomodoro_pause(self):
        if self.pomodoro.get("phase") not in {"work", "break"}:
            return
        now = time.time()
        paused_at = float(self.pomodoro.get("paused_at") or 0)
        if paused_at:
            self.pomodoro["end_ts"] += now - paused_at
            self.pomodoro["paused_at"] = 0.0
        else:
            self.pomodoro["paused_at"] = now
        self._update_pomodoro_view()
        self._refresh_status_item()

    def _stop_pomodoro(self):
        self.pomodoro.update({
            "phase": "idle", "end_ts": 0.0, "paused_at": 0.0, "session_id": "",
        })
        self._update_pomodoro_view()
        self._refresh_status_item()
        self._update_size()

    def _complete_pomodoro_phase(self):
        phase = self.pomodoro.get("phase")
        if phase not in {"work", "break"}:
            return
        completed_at = float(self.pomodoro.get("end_ts") or time.time())
        self.pomodoro["phase"] = "transition"
        next_phase = next_pomodoro_phase(
            phase, bool(self.settings.get("pomodoro_auto_cycle"))
        )
        if phase == "work":
            self._record_completed_pomodoro(completed_at)
            self._start_pomodoro_break()
            self._send_pomodoro_notification(
                self.tr("pomodoro_work_done"),
                self.tr(
                    "pomodoro_break_started",
                    minutes=max(1, int(self.settings["pomodoro_break_seconds"] / 60)),
                ),
                "work",
                self.pomodoro["session_id"],
            )
            return
        detail = (
            self.tr("pomodoro_work_started")
            if next_phase == "work"
            else self.tr("pomodoro_waiting")
        )
        if next_phase == "work":
            self._start_pomodoro_work()
        else:
            self.pomodoro.update({
                "phase": "ready", "end_ts": 0.0, "paused_at": 0.0,
                "session_id": uuid.uuid4().hex,
            })
            self._update_pomodoro_view()
            self._refresh_status_item()
            self._update_size()
        self._send_pomodoro_notification(
            self.tr("pomodoro_break_done"), detail, "break",
            self.pomodoro["session_id"],
        )

    def _update_pomodoro_view(self):
        if not getattr(self, "pomodoro_time_label", None):
            return
        phase = self.pomodoro.get("phase", "idle")
        paused = bool(self.pomodoro.get("paused_at"))
        if phase in {"work", "break"}:
            seconds = pomodoro_remaining(self.pomodoro)
        else:
            seconds = self.settings.get("pomodoro_work_seconds", 25 * 60)
        self.pomodoro_time_label.setStringValue_(fmt_pomodoro_remaining(seconds))
        labels = {
            "idle": "pomodoro_ready",
            "ready": "pomodoro_next",
            "work": "pomodoro_work",
            "break": "pomodoro_break",
        }
        self.pomodoro_phase_label.setStringValue_(self.tr(labels[phase]))
        self.pomodoro_today_label.setStringValue_(
            self.tr("pomodoro_today", count=self._today_pomodoro_count())
        )
        self.pomodoro_main_button.setTitle_(
            self.tr("pomodoro_resume" if paused else "pomodoro_pause")
            if phase in {"work", "break"}
            else self.tr("pomodoro_start")
        )
        active = phase in {"work", "break"}
        self.pomodoro_skip_button.setTitle_(
            self.tr("pomodoro_skip_break" if phase == "break" else "pomodoro_skip")
        )
        self.pomodoro_skip_button.setHidden_(phase not in {"work", "break"})
        self.pomodoro_stop_button.setHidden_(not active)
        color = (
            NSColor.colorWithSRGBRed_green_blue_alpha_(0.85, 0.41, 0.36, 1.0)
            if phase == "work"
            else NSColor.colorWithSRGBRed_green_blue_alpha_(0.41, 0.66, 0.46, 1.0)
            if phase == "break"
            else NSColor.controlAccentColor()
        )
        self.pomodoro_time_label.setTextColor_(color)

    # -- 时长拉杆与目标时间 -------------------------------------------------
    def _make_segmented_time_field(self, text, width, commit):
        field = self._make_time_label(text, 11.5, NSFontWeightMedium, width)
        editor = _TimeEditController.alloc().initWithField_commit_(field, commit)
        editor.setEventOwner_(self)
        field.setTimeController_(editor)
        field.setDelegate_(editor)
        return field, editor

    @staticmethod
    def _snap_minutes(minutes):
        """Keep the 24-hour slider usable: finer steps for shorter timers."""
        if minutes <= 60:
            return int(round(minutes))
        if minutes <= 300:
            return int(round(minutes / 5.0)) * 5
        return int(round(minutes / 15.0)) * 15

    def _set_pending_seconds(self, seconds, source=None):
        self._pending_seconds = max(0, min(MAX_DURATION_SECONDS, int(round(seconds))))
        if source != "slider":
            self.duration_slider.setDoubleValue_(
                slider_position_for_seconds(self._pending_seconds)
            )
        if source != "duration":
            self.duration_field.setStringValue_(fmt_remaining(self._pending_seconds))
        if source != "target":
            self.target_field.setStringValue_(
                fmt_clock_time(time.time() + self._pending_seconds)
            )

    def _slider_changed(self, sender):
        seconds = seconds_for_slider_position(sender.doubleValue())
        minutes = self._snap_minutes(seconds / 60.0)
        self._set_pending_seconds(minutes * 60, source="slider")

    def _duration_text_changed(self, text):
        try:
            seconds = parse_duration_text(text)
        except ValueError:
            return False
        self._set_pending_seconds(seconds, source="duration")
        self.duration_field.setStringValue_(fmt_remaining(self._pending_seconds))
        return True

    def _target_text_changed(self, text):
        now = time.time()
        try:
            target = parse_clock_text(text, now)
        except ValueError:
            return False
        self._set_pending_seconds(target - now, source="target")
        self.target_field.setStringValue_(fmt_clock_time(now + self._pending_seconds))
        return True

    # -- 启动倒计时 --------------------------------------------------------
    def _start_pending(self):
        if self._pending_seconds > 0:
            self._start_timer(self._pending_seconds)

    def _start_timer(self, seconds, label=None):
        label = (label if label is not None else self.input_field.stringValue()).strip()
        if not label:
            label = self._default_label()
        now = time.time()
        timer = {
            "id": uuid.uuid4().hex,
            "label": label,
            "kind": "countdown",
            "start_ts": now,
            "end_ts": now + int(seconds),
            "paused_at": 0.0,
            "pinned": False,
            "finished": False,
            "laps": [],
        }
        self._add_timer_row(timer)
        self.input_field.setStringValue_("")
        self.input_field.setPlaceholderString_(self.tr("timer_name"))
        self._persist()
        self._update_size()
        return timer

    def _start_stopwatch(self, label=None):
        label = (label if label is not None else self.input_field.stringValue()).strip()
        if not label:
            label = self._default_label()
        now = time.time()
        timer = {
            "id": uuid.uuid4().hex, "label": label, "kind": "stopwatch",
            "start_ts": now, "end_ts": 0.0, "paused_at": 0.0,
            "pinned": False, "finished": False, "laps": [],
        }
        self._add_timer_row(timer)
        self.input_field.setStringValue_("")
        self._persist()
        self._update_size()
        return timer

    def _default_label(self):
        used = {t.get("label") for t in self.timers}
        i = 1
        while True:
            candidate = self.tr("task", number=i)
            if candidate not in used:
                return candidate
            i += 1

    def _add_timer_row(self, timer):
        now = time.time()
        timer.setdefault("kind", "countdown")
        timer.setdefault("start_ts", now)
        timer.setdefault("end_ts", 0.0)
        timer.setdefault("paused_at", 0.0)
        timer.setdefault("pinned", False)
        timer.setdefault("finished", False)
        timer.setdefault("laps", [])
        countdown = timer["kind"] == "countdown"
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
        name.setToolTip_(f"{timer['label']}\n{self.tr('rename_tip')}")
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

        pin = _button(
            "★" if timer.get("pinned") else "☆",
            lambda s: self._toggle_pin(timer),
            actions,
            small=True,
            quiet=True,
        )
        pin.setToolTip_(self.tr("unpin") if timer.get("pinned") else self.tr("pin"))
        pin.heightAnchor().constraintEqualToConstant_(20).setActive_(True)
        top.addArrangedSubview_(pin)
        rowv.addArrangedSubview_(top)

        times = _hstack(5)
        remaining = self._make_time_label("00:00:00", 13, NSFontWeightSemibold, 76)
        remaining.setTextColor_(NSColor.controlAccentColor())
        remaining_editor = None
        if countdown:
            remaining_editor = _TimeEditController.alloc().initWithField_commit_(
                remaining, self._make_remaining_commit(timer)
            )
            remaining_editor.setEventOwner_(self)
            remaining.setTimeController_(remaining_editor)
            remaining.setDelegate_(remaining_editor)
            remaining.setToolTip_(self.tr("edit_remaining_tip"))
            actions.append(remaining_editor)
        times.addArrangedSubview_(remaining)
        times_spacer = NSView.alloc().init()
        times.addArrangedSubview_(times_spacer)
        times_spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)

        ends_label = _section_label(self.tr("ends_at"))
        target = self._make_time_label("00:00:00", 11.5, NSFontWeightMedium, 68)
        target.setTextColor_(NSColor.secondaryLabelColor())
        target_editor = None
        if countdown:
            target_editor = _TimeEditController.alloc().initWithField_commit_(
                target, self._make_target_commit(timer)
            )
            target_editor.setEventOwner_(self)
            target.setTimeController_(target_editor)
            target.setDelegate_(target_editor)
            target.setToolTip_(self.tr("edit_target_tip"))
            actions.append(target_editor)
        ends_label.setHidden_(not countdown)
        target.setHidden_(not countdown)
        times.addArrangedSubview_(ends_label)
        times.addArrangedSubview_(target)
        rowv.addArrangedSubview_(times)

        lap_label = _section_label("")
        lap_label.setHidden_(True)
        rowv.addArrangedSubview_(lap_label)

        bottom = _hstack(4)
        pause = _button(
            "▶" if timer_is_paused(timer) else "Ⅱ",
            lambda s: self._toggle_pause(timer),
            actions,
            small=True,
            quiet=True,
        )
        pause.setToolTip_(self.tr("resume") if timer_is_paused(timer) else self.tr("pause"))
        duplicate = _button(
            "⧉", lambda s: self._duplicate_timer(timer), actions, small=True, quiet=True
        )
        duplicate.setToolTip_(self.tr("duplicate"))
        lap = _button(self.tr("lap"), lambda s: self._record_lap(timer), actions, small=True, quiet=True)
        cancel = _button("×", self._make_cancel_cb(timer), actions, small=True, quiet=True)
        restart = _button(self.tr("restart"), self._make_restart_cb(timer), actions, small=True, quiet=True)
        done = _button(self.tr("checked"), self._make_cancel_cb(timer), actions, small=True, accent=True)
        restart.setHidden_(True)
        done.setHidden_(True)
        lap.setHidden_(countdown)
        for button in (pause, duplicate, lap, cancel, restart, done):
            button.heightAnchor().constraintEqualToConstant_(22).setActive_(True)
        for button in (pause, duplicate, cancel):
            button.widthAnchor().constraintEqualToConstant_(30).setActive_(True)

        bottom.addArrangedSubview_(lap)
        bottom.addArrangedSubview_(pause)
        bottom.addArrangedSubview_(duplicate)
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
        for row in (top, times, bottom):
            row.leadingAnchor().constraintEqualToAnchor_(rowv.leadingAnchor()).setActive_(True)
            row.trailingAnchor().constraintEqualToAnchor_(rowv.trailingAnchor()).setActive_(True)

        timer["view"] = card
        timer["card"] = card
        timer["remaining"] = remaining
        timer["remaining_editor"] = remaining_editor
        timer["target"] = target
        timer["target_editor"] = target_editor
        timer["ends_label"] = ends_label
        timer["name"] = name
        timer["rename"] = rename
        timer["pin"] = pin
        timer["lap_label"] = lap_label
        timer["pause"] = pause
        timer["duplicate"] = duplicate
        timer["lap"] = lap
        timer["cancel"] = cancel
        timer["restart"] = restart
        timer["done"] = done
        timer["actions"] = actions
        self.timers.append(timer)
        self._retain.extend(actions)
        if timer["finished"]:
            self._apply_finished_style(timer)
        else:
            self._apply_running_style(timer)
        self._update_row(timer)
        self._sort_timer_views()
        self._update_section()

    def _make_time_label(self, text, size, weight, width=76):
        field = _TimeField.alloc().initWithFrame_(NSMakeRect(0, 0, width, 20))
        field.setStringValue_(text)
        field.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(size, weight))
        field.setEditable_(False)
        field.setSelectable_(False)
        field.setBezeled_(False)
        field.setBordered_(False)
        field.setDrawsBackground_(False)
        field.setAlignment_(1)
        field.setFocusRingType_(NSFocusRingTypeNone)
        field.widthAnchor().constraintEqualToConstant_(width).setActive_(True)
        field.setContentHuggingPriority_forOrientation_(750, NSLayoutConstraintOrientationHorizontal)
        return field

    def _make_remaining_commit(self, timer):
        def commit(text):
            try:
                seconds = parse_duration_text(text)
            except ValueError:
                return False
            base = timer_reference_time(timer)
            timer["end_ts"] = base + seconds
            timer["start_ts"] = min(float(timer["start_ts"]), timer["end_ts"])
            self._apply_timer_change(timer)
            return True
        return commit

    def _make_target_commit(self, timer):
        def commit(text):
            try:
                target = parse_clock_text(text, timer_reference_time(timer))
            except ValueError:
                return False
            timer["end_ts"] = target
            timer["start_ts"] = min(float(timer["start_ts"]), timer["end_ts"])
            self._apply_timer_change(timer)
            return True
        return commit

    def _apply_timer_change(self, timer):
        """Re-evaluate a countdown after its start or end time changed."""
        if timer_remaining(timer) <= 0:
            if not timer.get("finished"):
                self._finish_timer(timer)
        else:
            if timer.get("finished"):
                timer["finished"] = False
                self._clear_delivered_notification(timer.get("id"))
                self._apply_running_style(timer)
            self._update_row(timer)
        self._persist()
        self._sort_timer_views()
        self._update_size()
        self._refresh_status_item()

    def _finish_timer(self, timer):
        timer["finished"] = True
        timer["paused_at"] = 0.0
        self._send_finish_notification(timer)
        self._apply_finished_style(timer)

    def _make_cancel_cb(self, timer):
        return lambda s: self._cancel_timer(timer)

    def _make_restart_cb(self, timer):
        return lambda s: self._restart_timer(timer)

    def _duplicate_timer(self, timer):
        if timer.get("kind") == "stopwatch":
            return self._start_stopwatch(timer["label"])
        return self._start_timer(timer_duration(timer), timer["label"])

    def _toggle_pin(self, timer):
        timer["pinned"] = not timer.get("pinned", False)
        timer["pin"].setTitle_("★" if timer["pinned"] else "☆")
        timer["pin"].setToolTip_(self.tr("unpin") if timer["pinned"] else self.tr("pin"))
        self._sort_timer_views()
        self._persist()

    def _toggle_pause(self, timer):
        if timer.get("finished"):
            return
        now = time.time()
        if timer_is_paused(timer):
            shift = now - float(timer["paused_at"])
            timer["start_ts"] = float(timer["start_ts"]) + shift
            if timer.get("end_ts"):
                timer["end_ts"] = float(timer["end_ts"]) + shift
            timer["paused_at"] = 0.0
            timer["pause"].setTitle_("Ⅱ")
            timer["pause"].setToolTip_(self.tr("pause"))
        else:
            timer["paused_at"] = now
            timer["pause"].setTitle_("▶")
            timer["pause"].setToolTip_(self.tr("resume"))
        self._update_row(timer)
        self._persist()
        self._sort_timer_views()
        self._refresh_status_item()

    def _record_lap(self, timer):
        if timer.get("kind") != "stopwatch" or timer.get("finished"):
            return
        timer.setdefault("laps", []).append(timer_elapsed(timer))
        self._update_row(timer)
        self._persist()

    def _sort_timer_views(self):
        if not getattr(self, "timers_stack", None):
            return
        def key(timer):
            pinned = 0 if timer.get("pinned") else 1
            finished = 1 if timer.get("finished") else 0
            if self.settings.get("sort_by_expiry") and timer.get("kind") == "countdown":
                order = timer_remaining(timer)
            else:
                order = float(timer.get("start_ts", 0))
            return pinned, finished, order
        self.timers.sort(key=key)
        for timer in self.timers:
            view = timer.get("view")
            if view is not None:
                self.timers_stack.removeArrangedSubview_(view)
                view.removeFromSuperview()
                self.timers_stack.addArrangedSubview_(view)
                self._fill_width(view)

    def _cancel_timer(self, timer):
        self._remove_timer(timer)
        self._persist()
        self._update_size()

    def _remove_timer(self, timer):
        for key in ("rename", "remaining_editor", "target_editor"):
            editor = timer.get(key)
            if editor is not None:
                editor.cancel()
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
        self._refresh_status_item()

    def _update_row(self, timer):
        remaining_editor = timer.get("remaining_editor")
        target_editor = timer.get("target_editor")
        if timer.get("kind") == "stopwatch":
            timer["remaining"].setStringValue_(fmt_remaining(timer_elapsed(timer)))
            timer["remaining"].setTextColor_(NSColor.controlAccentColor())
            laps = timer.get("laps", [])
            if laps:
                latest = laps[-1] - (laps[-2] if len(laps) > 1 else 0)
                timer["lap_label"].setStringValue_(self.tr("laps", count=len(laps), latest=fmt_remaining(latest)))
                timer["lap_label"].setHidden_(False)
            else:
                timer["lap_label"].setHidden_(True)
            return
        remaining = timer_remaining(timer)
        if remaining_editor is None or not remaining_editor.editing():
            timer["remaining"].setStringValue_(
                self.tr("finished") if timer.get("finished") else fmt_remaining(remaining)
            )
        if target_editor is None or not target_editor.editing():
            timer["target"].setStringValue_(fmt_clock_time(timer.get("end_ts") or time.time()))
        if timer.get("finished"):
            timer["remaining"].setTextColor_(NSColor.systemRedColor())
            return
        nearly_finished = remaining <= 10 and not timer_is_paused(timer)
        color = NSColor.systemRedColor() if nearly_finished else NSColor.controlAccentColor()
        timer["remaining"].setTextColor_(color)

    def _update_section(self):
        n = len(self.timers)
        self.section_label.setStringValue_(
            self.tr("empty") if n == 0 else self.tr("running", count=n)
        )

    def systemColorsDidChange_(self, _notification):
        """Refresh custom accent-colored elements after System Settings changes."""
        for timer in self.timers:
            self._update_row(timer)
        self._status_images.clear()
        self._status_signature = None
        self._update_pomodoro_view()
        self._refresh_status_item()

    # -- 计时循环 ----------------------------------------------------------
    def _start_ticker(self):
        self._ticker = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            0.5, self, "tick:", None, True
        )

    def _main_view_is_visible(self):
        popover_visible = bool(
            getattr(self, "popover", None) and self.popover.isShown()
        )
        preview_window = getattr(self, "_preview_window", None)
        preview_visible = bool(preview_window is not None and preview_window.isVisible())
        return popover_visible or preview_visible

    def tick_(self, _timer):
        newly_finished = []
        panel_visible = self._main_view_is_visible()
        pomodoro_active = self.pomodoro.get("phase") in {"work", "break"}
        if pomodoro_active and not self.pomodoro.get("paused_at"):
            if pomodoro_remaining(self.pomodoro) <= 0:
                self._complete_pomodoro_phase()
            elif panel_visible:
                self._update_pomodoro_view()
        for timer in self.timers:
            if timer.get("finished"):
                continue
            if panel_visible:
                self._update_row(timer)
            if timer.get("kind") == "countdown" and not timer_is_paused(timer) and timer_remaining(timer) <= 0:
                newly_finished.append(timer)
        for timer in newly_finished:
            self._finish_timer(timer)
        if newly_finished:
            self._persist()
            self._sort_timer_views()
            self._update_size()
        self._refresh_status_item()

    def _apply_finished_style(self, timer):
        editor = timer.get("remaining_editor")
        if editor is None or not editor.editing():
            timer["remaining"].setStringValue_(self.tr("finished"))
        timer["remaining"].setTextColor_(NSColor.systemRedColor())
        timer["card"].layer().setBorderWidth_(1.0)
        timer["card"].layer().setBorderColor_(
            NSColor.systemRedColor().colorWithAlphaComponent_(0.45).CGColor()
        )
        timer["pause"].setHidden_(True)
        timer["lap"].setHidden_(True)
        timer["duplicate"].setHidden_(False)
        timer["cancel"].setHidden_(True)
        timer["restart"].setHidden_(False)
        timer["done"].setHidden_(False)

    def _apply_running_style(self, timer):
        timer["card"].layer().setBorderWidth_(0.0)
        countdown = timer.get("kind") == "countdown"
        timer["lap"].setHidden_(countdown)
        timer["pause"].setHidden_(False)
        timer["pause"].setTitle_("▶" if timer_is_paused(timer) else "Ⅱ")
        timer["pause"].setToolTip_(self.tr("resume") if timer_is_paused(timer) else self.tr("pause"))
        timer["duplicate"].setHidden_(False)
        timer["cancel"].setHidden_(False)
        timer["restart"].setHidden_(True)
        timer["done"].setHidden_(True)

    def _restart_timer(self, timer):
        now = time.time()
        duration = timer_duration(timer)
        timer["finished"] = False
        timer["paused_at"] = 0.0
        timer["start_ts"] = now
        if timer.get("kind") == "stopwatch":
            timer["end_ts"] = 0.0
            timer["laps"] = []
        else:
            timer["end_ts"] = now + duration
        self._clear_delivered_notification(timer.get("id"))
        self._apply_running_style(timer)
        self._update_row(timer)
        self._persist()
        self._sort_timer_views()
        self._update_size()

    # -- iCloud KVS（可用时同步设置与聚合统计）-------------------------------
    def _setup_icloud_sync(self):
        if not getattr(sys, "frozen", False):
            return
        try:
            store_class = objc.lookUpClass("NSUbiquitousKeyValueStore")
            store = store_class.defaultStore()
            self._icloud_store = store
            NSNotificationCenter.defaultCenter().addObserver_selector_name_object_(
                self,
                "icloudStoreDidChange:",
                "NSUbiquitousKeyValueStoreDidChangeExternallyNotification",
                store,
            )
            store.synchronize()
            self._merge_icloud_payload(store.stringForKey_("multitimer.sync.v1"))
            self._refresh_synced_pomodoro_ui()
        except Exception:
            self._icloud_store = None

    def icloudStoreDidChange_(self, _notification):
        if self._icloud_store is None:
            return
        encoded = self._icloud_store.stringForKey_("multitimer.sync.v1")
        AppHelper.callAfter(self._apply_icloud_change, encoded)

    def _apply_icloud_change(self, encoded):
        should_write_back = self._merge_icloud_payload(encoded)
        self._refresh_synced_pomodoro_ui()
        if should_write_back:
            self._sync_to_icloud()

    def _refresh_synced_pomodoro_ui(self):
        if getattr(self, "_setting_controls", None):
            self._refresh_settings_controls()
        if getattr(self, "pomodoro_card", None) is not None:
            self.pomodoro_card.setHidden_(
                not self.settings.get("show_pomodoro", True)
            )
            self._update_pomodoro_view()

    def _icloud_payload(self):
        return json.dumps({
            "settings": {
                key: self.settings[key]
                for key in DEFAULT_SETTINGS
                if key in self.settings and key != "sync_revision"
            },
            "settings_revision": self._settings_revision,
            "pomodoro_stats": self.pomodoro_stats_snapshot(),
        }, ensure_ascii=False)

    def _merge_icloud_payload(self, encoded):
        if not encoded:
            return False
        try:
            payload = json.loads(str(encoded))
        except (TypeError, json.JSONDecodeError):
            return False
        stats_changed = False
        if not isinstance(payload, dict):
            return False
        remote_settings = payload.get("settings")
        raw_revision = payload.get("settings_revision") or 0
        try:
            remote_revision = float(raw_revision)
        except (TypeError, ValueError, OverflowError):
            return False
        if not math.isfinite(remote_revision) or remote_revision < 0:
            return False
        if isinstance(remote_settings, dict) and remote_revision > self._settings_revision:
            self.settings.update({
                key: value for key, value in remote_settings.items()
                if key in DEFAULT_SETTINGS and key != "sync_revision"
            })
            self._settings_revision = remote_revision
            self.settings["sync_revision"] = remote_revision
        remote_stats = payload.get("pomodoro_stats") if isinstance(payload, dict) else None
        if isinstance(remote_stats, dict):
            with self._stats_lock:
                for day, count in remote_stats.items():
                    if not isinstance(day, str) or not isinstance(count, (int, float)):
                        continue
                    if isinstance(count, bool) or not math.isfinite(float(count)):
                        continue
                    try:
                        remote_count = max(0, int(count))
                    except (OverflowError, ValueError):
                        continue
                    previous = int(self.pomodoro_stats.get(day, 0))
                    merged = max(previous, remote_count)
                    self.pomodoro_stats[day] = merged
                    stats_changed = stats_changed or merged != previous
                save_pomodoro_stats(self.pomodoro_stats)
        return stats_changed

    def _sync_to_icloud(self):
        if self._icloud_store is None:
            return
        try:
            self._icloud_store.setString_forKey_(
                self._icloud_payload(), "multitimer.sync.v1"
            )
            self._icloud_store.synchronize()
        except Exception:
            self._icloud_store = None

    # -- 通知 (UNUserNotificationCenter, 从 MultiTimer.app 发出) --------------
    def _setup_notifications(self):
        if not _can_use_user_notifications():
            self.notif_center = None
            return
        center = UNUserNotificationCenter.currentNotificationCenter()
        self.notif_center = center
        center.setDelegate_(self)
        center.getNotificationSettingsWithCompletionHandler_(
            lambda settings: AppHelper.callAfter(
                self._update_notification_permission, int(settings.authorizationStatus())
            )
        )
        check = UNNotificationAction.actionWithIdentifier_title_options_(
            _NOTIF_ACTION_CHECK, self.tr("checked").replace("✓ ", ""), UNNotificationActionOptionNone
        )
        category = UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
            _NOTIF_CATEGORY, [check], [], UNNotificationCategoryOptionNone
        )
        extend = UNNotificationAction.actionWithIdentifier_title_options_(
            _POMODORO_ACTION_EXTEND, self.tr("pomodoro_extend"),
            UNNotificationActionOptionNone,
        )
        pomodoro_category = (
            UNNotificationCategory.categoryWithIdentifier_actions_intentIdentifiers_options_(
                _POMODORO_NOTIF_CATEGORY, [extend], [], UNNotificationCategoryOptionNone
            )
        )
        center.setNotificationCategories_({category, pomodoro_category})

    def _update_notification_permission(self, status):
        if not getattr(self, "notification_warning", None):
            return
        self._notification_status = status
        show = status in (UNAuthorizationStatusDenied, UNAuthorizationStatusNotDetermined)
        self.notification_warning.setHidden_(not show)
        self.notification_settings_button.setTitle_(
            self.tr("notification_request") if status == UNAuthorizationStatusNotDetermined
            else self.tr("open_settings")
        )
        self._update_size()

    def _open_notification_settings(self):
        if getattr(self, "_notification_status", None) == UNAuthorizationStatusNotDetermined:
            self.notif_center.requestAuthorizationWithOptions_completionHandler_(
                UNAuthorizationOptionAlert | UNAuthorizationOptionSound,
                lambda granted, err: self.notif_center.getNotificationSettingsWithCompletionHandler_(
                    lambda settings: AppHelper.callAfter(
                        self._update_notification_permission, int(settings.authorizationStatus())
                    )
                ),
            )
            return
        self._open_url("x-apple.systempreferences:com.apple.Notifications-Settings.extension")

    def _send_pomodoro_notification(
        self, title, detail, completed_phase, target_session_id
    ):
        sound_name = "Glass" if completed_phase == "work" else "Ping"
        sound = NSSound.soundNamed_(sound_name)
        if sound is not None:
            sound.play()
        if getattr(self, "notif_center", None) is None:
            return
        content = UNMutableNotificationContent.alloc().init()
        content.setTitle_(title)
        content.setSubtitle_(self.tr("pomodoro"))
        content.setBody_(detail)
        content.setCategoryIdentifier_(_POMODORO_NOTIF_CATEGORY)
        content.setUserInfo_({
            "completed_phase": completed_phase,
            "target_session_id": target_session_id,
        })
        request = UNNotificationRequest.requestWithIdentifier_content_trigger_(
            f"pomodoro-{uuid.uuid4().hex}", content, None
        )
        self.notif_center.addNotificationRequest_withCompletionHandler_(
            request, lambda error: None
        )

    def _extend_pomodoro_by_five_minutes(self, target_session_id):
        if (
            not target_session_id
            or target_session_id != self.pomodoro.get("session_id")
        ):
            return
        if self.pomodoro.get("phase") not in {"work", "break"}:
            return
        self.pomodoro["end_ts"] = max(
            float(self.pomodoro.get("end_ts") or time.time()), time.time()
        ) + 5 * 60
        self._update_pomodoro_view()
        self._refresh_status_item()

    def _send_finish_notification(self, timer):
        if getattr(self, "notif_center", None) is None:
            return
        content = UNMutableNotificationContent.alloc().init()
        content.setTitle_(APP_NAME)
        content.setSubtitle_(timer["label"])
        content.setBody_(self.tr("time_up_body"))
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
            elif action_id == _POMODORO_ACTION_EXTEND:
                info = response.notification().request().content().userInfo()
                target_session_id = info.get("target_session_id") if info else None
                self._extend_pomodoro_by_five_minutes(target_session_id)
        finally:
            completion()

    # -- 弹出/收起 ---------------------------------------------------------
    def _toggle_popover(self):
        if self.popover.isShown():
            self.popover.close()
            return
        if time.time() - self._closed_at < 0.25:
            return
        for timer in self.timers:
            if not timer.get("finished"):
                self._update_row(timer)
        self._update_pomodoro_view()
        self._update_size()
        btn = self.status_item.button()
        self.popover.showRelativeToRect_ofView_preferredEdge_(btn.bounds(), btn, NSMinYEdge)
        NSApp.activateIgnoringOtherApps_(True)
        self.input_field.window().makeFirstResponder_(self.input_field)

    def _show_preview_window(self):
        """Show the production content in a normal window for visual QA only."""
        self.target_field.setStringValue_("15:30:00")
        preview_phase = os.environ.get("MULTITIMER_PREVIEW_POMODORO")
        if preview_phase in {"work", "break"}:
            self.pomodoro.update({
                "phase": preview_phase,
                "end_ts": time.time() + 12 * 60 + 34,
                "paused_at": 0.0,
            })
            self._update_pomodoro_view()
            self._refresh_status_item()
        preview_view = self.content_view
        if os.environ.get("MULTITIMER_PREVIEW_VIEW") == "settings":
            if not getattr(self, "_settings_vc", None):
                self._build_settings_view()
            self._refresh_settings_controls()
            preview_view = self._settings_content_view
        preview_view.layoutSubtreeIfNeeded()
        size = preview_view.fittingSize()
        frame = NSMakeRect(0, 0, size.width, size.height)
        style = NSWindowStyleMaskTitled | NSWindowStyleMaskClosable
        window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            frame, style, NSBackingStoreBuffered, False
        )
        window.setTitle_(APP_NAME)
        window.setContentView_(preview_view)
        window.center()
        window.makeKeyAndOrderFront_(None)
        NSApp.activateIgnoringOtherApps_(True)
        self._preview_window = window
        snapshot_path = os.environ.get("MULTITIMER_SNAPSHOT_PATH")
        if snapshot_path:
            self._save_preview_snapshot(snapshot_path, preview_view)

    def _save_preview_snapshot(self, snapshot_path, view=None):
        """Render the preview content for website and README screenshots."""
        view = view or self.content_view
        view.setWantsLayer_(True)
        view.layer().setBackgroundColor_(NSColor.windowBackgroundColor().CGColor())
        view.layoutSubtreeIfNeeded()
        bounds = view.bounds()
        bitmap = view.bitmapImageRepForCachingDisplayInRect_(bounds)
        view.cacheDisplayInRect_toBitmapImageRep_(bounds, bitmap)
        data = bitmap.representationUsingType_properties_(NSBitmapImageFileTypePNG, {})
        Path(snapshot_path).write_bytes(bytes(data))

    def popoverDidClose_(self, _notification):
        self._closed_at = time.time()
        if getattr(self, "popover", None) is not None and getattr(self, "_vc", None) is not None:
            self.popover.setContentViewController_(self._vc)
            self._fit_popover_to(self.content_view)

    def _update_size(self):
        current = self.popover.contentViewController().view() if getattr(self, "popover", None) else self.content_view
        self._fit_popover_to(current)

    def _fit_popover_to(self, view):
        view.layoutSubtreeIfNeeded()
        self.popover.setContentSize_(view.fittingSize())

    def _persist(self):
        save_state(self.timers, self._skipped_update, self.settings)
        self._sync_to_icloud()

    def _quit(self):
        self._persist()
        NSApp.terminate_(None)

    def applicationWillTerminate_(self, _notification):
        if self._did_finish_launching:
            self._persist()
        if self._key_monitor is not None:
            NSEvent.removeMonitor_(self._key_monitor)
            self._key_monitor = None
        if self._stats_server is not None:
            self._stats_server.shutdown()
            self._stats_server.server_close()
            self._stats_server = None
        if self._icloud_store is not None:
            NSNotificationCenter.defaultCenter().removeObserver_(self)
        manager = NSAppleEventManager.sharedAppleEventManager()
        manager.removeEventHandlerForEventClass_andEventID_(
            int.from_bytes(b"GURL", "big"), int.from_bytes(b"GURL", "big")
        )
        if self._control_server is not None:
            self._control_server.shutdown()
            self._control_server.server_close()
        try:
            socket_stat = CONTROL_SOCKET_PATH.stat()
            identity = (socket_stat.st_dev, socket_stat.st_ino)
            if identity == self._control_socket_identity:
                CONTROL_SOCKET_PATH.unlink()
        except OSError:
            pass
        if self._control_lock is not None:
            self._control_lock.close()
            self._control_lock = None


def main():
    if len(sys.argv) > 1 and sys.argv[1] in {
        "start", "list", "pause", "cancel", "pomodoro", "help", "--help", "-h",
    }:
        raise SystemExit(_run_cli(sys.argv[1:]))
    if _relaunch_via_launchservices_if_needed():
        return
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
