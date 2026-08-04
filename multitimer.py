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
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import objc
from Foundation import (
    NSObject,
    NSTimer,
    NSMakeRect,
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
    NSControlStateValueOn,
    NSControlStateValueOff,
    NSSwitchButton,
    NSImageLeft,
    NSImageOnly,
)

APP_NAME = "MultiTimer"
APP_VERSION = "0.4.2"
# macOS 26 can retain a broken Control Center visibility record for a status
# item even after the app is reinstalled.  Use a fresh, status-bar-specific
# identity for the production app so upgrades are not tied to that stale entry.
APP_BUNDLE_ID = "io.github.echoforger.multitimer.menuapp2"
# A stable, explicit identity lets Control Center restore the status item
# instead of treating every launch as a new ephemeral host. This new app
# identity is intentionally different from legacy records that macOS may have
# remembered as hidden. Keep this value stable across future releases.
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
DEFAULT_PRESETS = [
    {"name": "1min", "seconds": 60},
    {"name": "5min", "seconds": 300},
    {"name": "10min", "seconds": 600},
    {"name": "15min", "seconds": 900},
    {"name": "30min", "seconds": 1800},
]

DEFAULT_SETTINGS = {
    "show_remaining": False,
    "show_count": False,
    "sort_by_expiry": True,
}

STRINGS = {
    "zh": {
        "timer_name": "计时名称（可选）", "quick_start": "快速开始", "edit": "编辑",
        "custom": "自定义", "minutes": "分钟", "start": "开始", "stopwatch": "秒表",
        "empty": "暂无进行中的计时器", "running": "进行中 · {count}",
        "task": "任务 {number}", "rename_tip": "双击或用力按压以重命名",
        "restart": "重新计时", "checked": "✓ 已检查", "finished": "已结束",
        "pause": "暂停", "resume": "继续", "lap": "计圈", "laps": "{count} 圈 · 最近 {latest}",
        "duplicate": "复制", "decrease": "减少", "pin": "置顶", "unpin": "取消置顶",
        "settings": "设置", "quit": "退出 MultiTimer", "about": "关于 MultiTimer",
        "notification_denied": "通知已关闭，计时结束时可能无法提醒。", "open_settings": "打开系统设置",
        "settings_title": "MultiTimer 设置", "launch_at_login": "登录时自动启动",
        "show_remaining": "菜单栏显示最近剩余时间", "show_count": "菜单栏显示计时器数量",
        "sort_by_expiry": "最近到期优先", "language": "应用语言",
        "language_detail": "由 macOS 管理。", "open_language_settings": "系统设置…",
        "back": "返回", "save": "保存", "cancel": "取消",
        "time_up_body": "时间到，点击“已检查”移除", "time_up": "时间到",
        "confirm_finish": "剩余时间将变为零", "confirm_finish_detail": "要立即结束“{name}”吗？",
        "finish_now": "立即结束", "status_hidden": "菜单栏图标没有显示",
        "status_hidden_detail": "MultiTimer 已尝试恢复图标。若仍未显示，请在系统设置的控制中心中允许 MultiTimer 显示在菜单栏。",
        "retry": "重新创建图标", "later": "稍后", "notification_request": "允许通知",
        "source": "安装来源：{source}", "version": "版本 {version}", "development": "开发模式", "unknown": "未知",
        "tagline": "多个倒计时，一个节奏。\n原生 macOS 菜单栏多任务倒计时器。",
        "privacy": "MIT License · 无账户 · 无遥测 · 数据仅在本机",
        "check_updates": "检查更新", "homepage": "项目主页", "close": "关闭",
        "update_busy": "更新正在进行", "update_busy_detail": "请稍候，MultiTimer 会在完成后通知你。",
        "checking": "正在检查 MultiTimer 更新…", "check_failed": "检查更新失败",
        "latest": "已是最新版", "latest_detail": "你正在使用 MultiTimer {version}。",
        "found_update": "发现 MultiTimer {version}", "current_version": "当前版本：{version}", "whats_new": "新版特性",
        "update_now": "立即更新", "skip_version": "跳过这个版本", "brew_will_run": "Homebrew 将在后台运行：",
        "update_failed": "更新未完成", "release_page": "打开 Release 页", "update_installed": "更新已安装",
        "update_installed_detail": "MultiTimer {version} 已通过 {source} 安装完成。重新启动后生效。",
        "restart_now": "现在重新启动", "edit_presets": "编辑预设", "preset_help": "每行一个：名称=分钟（例如 5min=5）",
    },
    "en": {
        "timer_name": "Timer name (optional)", "quick_start": "Quick Start", "edit": "Edit",
        "custom": "Custom", "minutes": "min", "start": "Start", "stopwatch": "Stopwatch",
        "empty": "No active timers", "running": "Active · {count}",
        "task": "Timer {number}", "rename_tip": "Double-click or Force Click to rename",
        "restart": "Restart", "checked": "✓ Done", "finished": "Finished",
        "pause": "Pause", "resume": "Resume", "lap": "Lap", "laps": "{count} laps · latest {latest}",
        "duplicate": "Duplicate", "decrease": "Reduce", "pin": "Pin", "unpin": "Unpin",
        "settings": "Settings", "quit": "Quit MultiTimer", "about": "About MultiTimer",
        "notification_denied": "Notifications are off, so completed timers may not alert you.", "open_settings": "Open Settings",
        "settings_title": "MultiTimer Settings", "launch_at_login": "Launch at Login",
        "show_remaining": "Show nearest remaining time", "show_count": "Show active timer count",
        "sort_by_expiry": "Sort by nearest expiry", "language": "App Language",
        "language_detail": "Managed by macOS.", "open_language_settings": "System Settings…",
        "back": "Back", "save": "Save", "cancel": "Cancel",
        "time_up_body": "Time is up. Click Done to remove it.", "time_up": "Time's up",
        "confirm_finish": "The remaining time will reach zero", "confirm_finish_detail": "Finish “{name}” now?",
        "finish_now": "Finish Now", "status_hidden": "Menu bar icon is not visible",
        "status_hidden_detail": "MultiTimer tried to restore its icon. If it is still missing, allow MultiTimer in System Settings > Control Center.",
        "retry": "Recreate Icon", "later": "Later", "notification_request": "Allow Notifications",
        "source": "Install source: {source}", "version": "Version {version}", "development": "Development", "unknown": "Unknown",
        "tagline": "Multiple timers, one rhythm.\nA native macOS menu bar timer.",
        "privacy": "MIT License · No account · No telemetry · Local data only",
        "check_updates": "Check for Updates", "homepage": "Project Home", "close": "Close",
        "update_busy": "Update in Progress", "update_busy_detail": "MultiTimer will notify you when it finishes.",
        "checking": "Checking for MultiTimer updates…", "check_failed": "Update Check Failed",
        "latest": "You're Up to Date", "latest_detail": "You're using MultiTimer {version}.",
        "found_update": "MultiTimer {version} is Available", "current_version": "Current version: {version}", "whats_new": "What's New",
        "update_now": "Update Now", "skip_version": "Skip This Version", "brew_will_run": "Homebrew will run in the background:",
        "update_failed": "Update Not Completed", "release_page": "Open Release Page", "update_installed": "Update Installed",
        "update_installed_detail": "MultiTimer {version} was installed via {source}. Restart to use it.",
        "restart_now": "Restart Now", "edit_presets": "Edit Presets", "preset_help": "One per line: name=minutes (for example 5min=5)",
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
    query = parse_qs(parsed.query)
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
    if seconds <= 0:
        raise ValueError("A positive minutes or seconds value is required")
    return {"command": "start", "kind": "countdown", "name": name, "seconds": int(round(seconds))}


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
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    for path in (executable, *executable.parents):
        if path.suffix.lower() == ".app" and (path / "Contents" / "MacOS").is_dir():
            return path
    return None


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


def fmt_status_remaining(seconds: float) -> str:
    """Format menu-bar time without seconds using a stable HH:MM width."""
    total_minutes = max(0, int(math.ceil(max(0.0, float(seconds)) / 60.0)))
    hours, minutes = divmod(total_minutes, 60)
    return f"{hours:02d}:{minutes:02d}"


def fmt_duration(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds % 60 == 0:
        return f"{seconds // 60}min"
    return fmt_remaining(seconds)


_NOTIF_CATEGORY = "TIMER_DONE"
_NOTIF_ACTION_CHECK = "MARK_CHECKED"


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {
            "presets": [dict(p) for p in DEFAULT_PRESETS], "timers": [],
            "settings": dict(DEFAULT_SETTINGS), "skipped_update": "",
        }
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {
            "presets": [dict(p) for p in DEFAULT_PRESETS], "timers": [],
            "settings": dict(DEFAULT_SETTINGS), "skipped_update": "",
        }
    presets = data.get("presets") or [dict(p) for p in DEFAULT_PRESETS]
    now = time.time()
    timers = []
    for raw in data.get("timers", []):
        timer = dict(raw)
        timer.setdefault("kind", "countdown")
        timer.setdefault("duration", 0)
        timer.setdefault("pinned", False)
        timer.setdefault("paused", False)
        timer.setdefault("finished", False)
        timer.setdefault("created_ts", now)
        timer.setdefault("laps", [])
        if timer["kind"] == "stopwatch":
            timer.setdefault("elapsed_before", 0.0)
            timer.setdefault("start_ts", now)
            timers.append(timer)
        elif timer.get("paused") or timer.get("finished") or timer.get("end_ts", 0) > now:
            timers.append(timer)
    skipped_update = str(data.get("skipped_update") or "")
    settings = dict(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in (data.get("settings") or {}).items() if k in settings})
    return {"presets": presets, "timers": timers, "settings": settings, "skipped_update": skipped_update}


def _persistent_timer(timer: dict) -> dict:
    keys = (
        "id", "label", "kind", "duration", "end_ts", "created_ts", "pinned",
        "paused", "paused_remaining", "finished", "start_ts", "elapsed_before", "laps",
    )
    return {key: timer[key] for key in keys if key in timer}


def save_state(presets: list, timers: list, skipped_update="", settings=None) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": 2,
        "presets": presets,
        "timers": [_persistent_timer(t) for t in timers],
        "skipped_update": skipped_update,
        "settings": dict(settings or DEFAULT_SETTINGS),
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


def _send_cli_request(request: dict, launch=True) -> dict:
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
        print("Usage:\n  multitimer start [NAME] MINUTES\n  multitimer start --stopwatch [NAME]\n  multitimer list\n  multitimer pause ID_OR_NAME\n  multitimer cancel ID_OR_NAME")
        return 0
    request = {"command": command}
    if command == "start":
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
            except ValueError:
                print("the last start argument must be MINUTES", file=sys.stderr)
                return 2
            request.update({"kind": "countdown", "name": " ".join(args[:-1]).strip(), "seconds": int(round(minutes * 60))})
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
    if command == "list":
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
        self._field.setToolTip_(f"{value}\n{self._owner.tr('rename_tip')}")
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
        self._skipped_update = state["skipped_update"]
        self.settings = state["settings"]
        self.language = _language_for_settings(self.settings)
        self.timers = []          # dict: id/label/end_ts/duration/view/name/progress/actions
        self._retain = []         # 全局 target 保活
        self._closed_at = 0.0
        self._did_finish_launching = False
        self._update_in_progress = False
        self._control_server = None
        self._status_signature = None
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

    def _refresh_status_item(self):
        if not getattr(self, "status_item", None):
            return
        active = [t for t in self.timers if not t.get("finished")]
        parts = []
        if self.settings.get("show_remaining") and active:
            countdowns = [t for t in active if t.get("kind", "countdown") == "countdown"]
            if countdowns:
                nearest = min(countdowns, key=lambda item: self._timer_remaining(item))
                parts.append(fmt_status_remaining(self._timer_remaining(nearest)))
        if self.settings.get("show_count"):
            parts.append(str(len(active)))
        title = " · ".join(parts)
        signature = (title, bool(title))
        if signature == self._status_signature:
            return
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
            if CONTROL_SOCKET_PATH.exists():
                CONTROL_SOCKET_PATH.unlink()
            server = _ControlServer(str(CONTROL_SOCKET_PATH), _ControlHandler)
            server.app = self
            os.chmod(CONTROL_SOCKET_PATH, 0o600)
            self._control_server = server
            threading.Thread(target=server.serve_forever, daemon=True).start()
        except Exception:
            self._control_server = None

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
                seconds = int(request.get("seconds") or 0)
                if seconds <= 0:
                    raise ValueError("Duration must be positive")
                timer = self._start_timer(seconds, label)
            return {"ok": True, "message": f"Started {timer['label']}", "id": timer["id"]}
        if command == "list":
            rows = []
            for timer in self.timers:
                rows.append({
                    "id": timer["id"], "label": timer["label"], "kind": timer.get("kind", "countdown"),
                    "paused": timer.get("paused", False), "time": fmt_remaining(self._timer_display_seconds(timer)),
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
        for key in ("show_remaining", "show_count", "sort_by_expiry"):
            controls[key].setState_(
                NSControlStateValueOn if self.settings.get(key) else NSControlStateValueOff
            )

    def _boolean_setting_changed(self, key, sender):
        self.settings[key] = sender.state() == NSControlStateValueOn
        self._persist()
        if key == "sort_by_expiry":
            self._sort_timer_views()
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
        self.input_field = NSTextField.textFieldWithString_("")
        self.input_field.setPlaceholderString_(self.tr("timer_name"))
        self.input_field.setFont_(NSFont.systemFontOfSize_(12))
        self.input_field.heightAnchor().constraintEqualToConstant_(25).setActive_(True)
        root.addArrangedSubview_(self.input_field)
        self._fill_width(self.input_field)

        # 快速开始
        presets_header = _hstack(6)
        presets_header.addArrangedSubview_(_section_label(self.tr("quick_start")))
        preset_spacer = NSView.alloc().init()
        presets_header.addArrangedSubview_(preset_spacer)
        preset_spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        edit_btn = _button(self.tr("edit"), lambda s: self._edit_presets(), self._retain, small=True, quiet=True)
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
        custom_label = NSTextField.labelWithString_(self.tr("custom"))
        custom_label.setFont_(NSFont.systemFontOfSize_weight_(11.5, NSFontWeightMedium))
        tools.addArrangedSubview_(custom_label)
        tools_spacer = NSView.alloc().init()
        tools.addArrangedSubview_(tools_spacer)
        tools_spacer.setContentHuggingPriority_forOrientation_(1, NSLayoutConstraintOrientationHorizontal)
        self.custom_field = NSTextField.textFieldWithString_("5")
        self.custom_field.setAlignment_(1)
        cf_w = self.custom_field.widthAnchor().constraintEqualToConstant_(44)
        cf_w.setActive_(True)
        min_lbl = NSTextField.labelWithString_(self.tr("minutes"))
        min_lbl.setTextColor_(NSColor.secondaryLabelColor())
        stopwatch_btn = _button(self.tr("stopwatch"), lambda s: self._start_stopwatch(), self._retain, small=True)
        add_btn = _button(self.tr("start"), lambda s: self._start_custom(), self._retain, accent=True, small=True)
        tools.addArrangedSubview_(self.custom_field)
        tools.addArrangedSubview_(min_lbl)
        tools.addArrangedSubview_(stopwatch_btn)
        tools.addArrangedSubview_(add_btn)
        self.custom_field.heightAnchor().constraintEqualToConstant_(22).setActive_(True)
        _embed_with_insets(custom_card, tools, top=5, right=7, bottom=5, left=9)
        root.addArrangedSubview_(custom_card)
        self._fill_width(custom_card)

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
        alert.setMessageText_(self.tr("edit_presets"))
        alert.setInformativeText_(self.tr("preset_help"))
        alert.addButtonWithTitle_(self.tr("save"))
        alert.addButtonWithTitle_(self.tr("cancel"))
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

    def _start_timer(self, seconds, label=None):
        label = (label if label is not None else self.input_field.stringValue()).strip()
        if not label:
            label = self._default_label()
        now = time.time()
        timer = {
            "id": uuid.uuid4().hex,
            "label": label,
            "kind": "countdown",
            "duration": int(seconds),
            "end_ts": now + seconds,
            "created_ts": now,
            "pinned": False,
            "paused": False,
            "finished": False,
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
            "duration": 0, "start_ts": now, "elapsed_before": 0.0,
            "created_ts": now, "pinned": False, "paused": False,
            "finished": False, "laps": [],
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
        timer.setdefault("duration", 0)
        timer.setdefault("created_ts", now)
        timer.setdefault("pinned", False)
        timer.setdefault("paused", False)
        timer.setdefault("finished", False)
        timer.setdefault("laps", [])
        if timer["kind"] == "stopwatch":
            timer.setdefault("start_ts", now)
            timer.setdefault("elapsed_before", 0.0)
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

        pin = _button("★" if timer.get("pinned") else "☆", lambda s: self._toggle_pin(timer), actions, small=True, quiet=True)
        pin.setToolTip_(self.tr("unpin") if timer.get("pinned") else self.tr("pin"))
        pin.heightAnchor().constraintEqualToConstant_(20).setActive_(True)
        top.addArrangedSubview_(pin)

        remaining = NSTextField.labelWithString_("--:--")
        remaining.setFont_(NSFont.monospacedDigitSystemFontOfSize_weight_(13, NSFontWeightSemibold))
        remaining.setTextColor_(NSColor.controlAccentColor())
        remaining.setContentHuggingPriority_forOrientation_(750, NSLayoutConstraintOrientationHorizontal)
        top.addArrangedSubview_(remaining)
        rowv.addArrangedSubview_(top)

        progress = _ProgressView.alloc().init()
        progress.heightAnchor().constraintEqualToConstant_(3).setActive_(True)
        progress.setHidden_(timer["kind"] == "stopwatch")
        rowv.addArrangedSubview_(progress)

        lap_label = _section_label("")
        lap_label.setHidden_(True)
        rowv.addArrangedSubview_(lap_label)

        bottom = _hstack(4)
        decrease = _button("−", lambda s: self._choose_decrease(timer), actions, small=True, quiet=True)
        plus1 = _button("＋1m", self._make_extend_cb(timer, 60), actions, small=True, quiet=True)
        plus10 = _button("＋10m", self._make_extend_cb(timer, 600), actions, small=True, quiet=True)
        plus60 = _button("＋1h", self._make_extend_cb(timer, 3600), actions, small=True, quiet=True)
        pause = _button("▶" if timer.get("paused") else "Ⅱ", lambda s: self._toggle_pause(timer), actions, small=True, quiet=True)
        pause.setToolTip_(self.tr("resume") if timer.get("paused") else self.tr("pause"))
        duplicate = _button("⧉", lambda s: self._duplicate_timer(timer), actions, small=True, quiet=True)
        duplicate.setToolTip_(self.tr("duplicate"))
        lap = _button(self.tr("lap"), lambda s: self._record_lap(timer), actions, small=True, quiet=True)
        cancel = _button("×", self._make_cancel_cb(timer), actions, small=True, quiet=True)
        restart = _button(self.tr("restart"), self._make_restart_cb(timer), actions, small=True, quiet=True)
        done = _button(self.tr("checked"), self._make_cancel_cb(timer), actions, small=True, accent=True)
        restart.setHidden_(True)
        done.setHidden_(True)
        countdown = timer["kind"] == "countdown"
        decrease.setHidden_(not countdown)
        plus1.setHidden_(not countdown)
        plus10.setHidden_(not countdown)
        plus60.setHidden_(not countdown)
        lap.setHidden_(countdown)
        for button in (decrease, plus1, plus10, plus60, pause, duplicate, lap, cancel, restart, done):
            button.heightAnchor().constraintEqualToConstant_(22).setActive_(True)
        for button in (pause, duplicate, cancel):
            button.widthAnchor().constraintEqualToConstant_(30).setActive_(True)

        bottom.addArrangedSubview_(decrease)
        bottom.addArrangedSubview_(plus1)
        bottom.addArrangedSubview_(plus10)
        bottom.addArrangedSubview_(plus60)
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
        timer["pin"] = pin
        timer["lap_label"] = lap_label
        timer["decrease"] = decrease
        timer["plus1"] = plus1
        timer["plus10"] = plus10
        timer["plus60"] = plus60
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

    def _make_extend_cb(self, timer, seconds):
        return lambda s: self._extend_timer(timer, seconds)

    def _make_cancel_cb(self, timer):
        return lambda s: self._cancel_timer(timer)

    def _make_restart_cb(self, timer):
        return lambda s: self._restart_timer(timer)

    def _extend_timer(self, timer, seconds):
        if timer.get("kind") != "countdown":
            return
        if timer.get("paused"):
            timer["paused_remaining"] = max(0, timer.get("paused_remaining", 0)) + seconds
        else:
            timer["end_ts"] += seconds
        timer["duration"] += seconds
        self._update_row(timer)
        self._persist()
        self._sort_timer_views()

    def _choose_decrease(self, timer):
        response = self._show_alert(
            self.tr("decrease"), timer["label"],
            ("−1 min", "−5 min", "−10 min", self.tr("cancel")),
        )
        if response not in (1000, 1001, 1002):
            return
        self._decrease_timer(timer, (60, 300, 600)[response - 1000])

    def _decrease_timer(self, timer, seconds):
        remaining = self._timer_remaining(timer)
        if seconds >= remaining:
            response = self._show_alert(
                self.tr("confirm_finish"), self.tr("confirm_finish_detail", name=timer["label"]),
                (self.tr("finish_now"), self.tr("cancel")),
            )
            if response != 1000:
                return
            if timer.get("paused"):
                timer["paused_remaining"] = 0
            else:
                timer["end_ts"] = time.time()
            timer["finished"] = True
            self._send_finish_notification(timer)
            self._apply_finished_style(timer)
        elif timer.get("paused"):
            timer["paused_remaining"] = remaining - seconds
        else:
            timer["end_ts"] -= seconds
        if not timer.get("finished"):
            self._update_row(timer)
        self._persist()
        self._sort_timer_views()

    def _duplicate_timer(self, timer):
        if timer.get("kind") == "stopwatch":
            return self._start_stopwatch(timer["label"])
        return self._start_timer(timer["duration"], timer["label"])

    def _toggle_pin(self, timer):
        timer["pinned"] = not timer.get("pinned", False)
        timer["pin"].setTitle_("★" if timer["pinned"] else "☆")
        timer["pin"].setToolTip_(self.tr("unpin") if timer["pinned"] else self.tr("pin"))
        self._sort_timer_views()
        self._persist()

    def _timer_remaining(self, timer):
        if timer.get("kind", "countdown") != "countdown":
            return 0.0
        if timer.get("paused"):
            return max(0.0, float(timer.get("paused_remaining", 0)))
        return max(0.0, float(timer.get("end_ts", 0)) - time.time())

    def _timer_elapsed(self, timer):
        elapsed = float(timer.get("elapsed_before", 0))
        if not timer.get("paused"):
            elapsed += max(0.0, time.time() - float(timer.get("start_ts", time.time())))
        return elapsed

    def _timer_display_seconds(self, timer):
        return self._timer_elapsed(timer) if timer.get("kind") == "stopwatch" else self._timer_remaining(timer)

    def _toggle_pause(self, timer):
        if timer.get("finished"):
            return
        now = time.time()
        if timer.get("paused"):
            timer["paused"] = False
            if timer.get("kind") == "stopwatch":
                timer["start_ts"] = now
            else:
                timer["end_ts"] = now + float(timer.get("paused_remaining", 0))
            timer["pause"].setTitle_("Ⅱ")
            timer["pause"].setToolTip_(self.tr("pause"))
        else:
            if timer.get("kind") == "stopwatch":
                timer["elapsed_before"] = self._timer_elapsed(timer)
            else:
                timer["paused_remaining"] = self._timer_remaining(timer)
            timer["paused"] = True
            timer["pause"].setTitle_("▶")
            timer["pause"].setToolTip_(self.tr("resume"))
        self._update_row(timer)
        self._persist()
        self._refresh_status_item()

    def _record_lap(self, timer):
        if timer.get("kind") != "stopwatch" or timer.get("finished"):
            return
        elapsed = self._timer_elapsed(timer)
        timer.setdefault("laps", []).append(elapsed)
        self._update_row(timer)
        self._persist()

    def _sort_timer_views(self):
        if not getattr(self, "timers_stack", None):
            return
        def key(timer):
            pinned = 0 if timer.get("pinned") else 1
            finished = 1 if timer.get("finished") else 0
            if self.settings.get("sort_by_expiry") and timer.get("kind") == "countdown":
                order = self._timer_remaining(timer)
            else:
                order = float(timer.get("created_ts", 0))
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
        if timer.get("kind") == "stopwatch":
            elapsed = self._timer_elapsed(timer)
            timer["remaining"].setStringValue_(fmt_remaining(elapsed))
            timer["remaining"].setTextColor_(NSColor.controlAccentColor())
            laps = timer.get("laps", [])
            if laps:
                latest = laps[-1] - (laps[-2] if len(laps) > 1 else 0)
                timer["lap_label"].setStringValue_(self.tr("laps", count=len(laps), latest=fmt_remaining(latest)))
                timer["lap_label"].setHidden_(False)
            else:
                timer["lap_label"].setHidden_(True)
            return
        remaining = self._timer_remaining(timer)
        timer["remaining"].setStringValue_(fmt_remaining(remaining))
        frac = max(0.0, min(1.0, remaining / max(1, timer["duration"])))
        timer["progress"].setDoubleValue_(frac * 1000.0)
        color = NSColor.systemRedColor() if remaining <= 10 and not timer.get("paused") else NSColor.controlAccentColor()
        timer["remaining"].setTextColor_(color)

    def _update_section(self):
        n = len(self.timers)
        self.section_label.setStringValue_(
            self.tr("empty") if n == 0 else self.tr("running", count=n)
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
        panel_visible = bool(getattr(self, "popover", None) and self.popover.isShown())
        for timer in self.timers:
            if timer.get("finished"):
                continue
            if panel_visible:
                self._update_row(timer)
            if timer.get("kind") == "countdown" and not timer.get("paused") and self._timer_remaining(timer) <= 0:
                newly_finished.append(timer)
        for timer in newly_finished:
            self._send_finish_notification(timer)
            timer["finished"] = True
            self._apply_finished_style(timer)
        if newly_finished:
            self._persist()
            self._sort_timer_views()
            self._update_size()
        self._refresh_status_item()

    def _apply_finished_style(self, timer):
        timer["remaining"].setStringValue_(self.tr("finished"))
        timer["remaining"].setTextColor_(NSColor.systemRedColor())
        timer["progress"].setDoubleValue_(0.0)
        timer["card"].layer().setBorderWidth_(1.0)
        timer["card"].layer().setBorderColor_(
            NSColor.systemRedColor().colorWithAlphaComponent_(0.45).CGColor()
        )
        for key in ("decrease", "plus1", "plus10", "plus60", "pause", "lap"):
            timer[key].setHidden_(True)
        timer["duplicate"].setHidden_(False)
        timer["cancel"].setHidden_(True)
        timer["restart"].setHidden_(False)
        timer["done"].setHidden_(False)

    def _apply_running_style(self, timer):
        timer["card"].layer().setBorderWidth_(0.0)
        countdown = timer.get("kind") == "countdown"
        timer["decrease"].setHidden_(not countdown)
        timer["plus1"].setHidden_(not countdown)
        timer["plus10"].setHidden_(not countdown)
        timer["plus60"].setHidden_(not countdown)
        timer["lap"].setHidden_(countdown)
        timer["pause"].setHidden_(False)
        timer["pause"].setTitle_("▶" if timer.get("paused") else "Ⅱ")
        timer["pause"].setToolTip_(self.tr("resume") if timer.get("paused") else self.tr("pause"))
        timer["duplicate"].setHidden_(False)
        timer["cancel"].setHidden_(False)
        timer["restart"].setHidden_(True)
        timer["done"].setHidden_(True)

    def _restart_timer(self, timer):
        timer["finished"] = False
        timer["paused"] = False
        if timer.get("kind") == "stopwatch":
            timer["start_ts"] = time.time()
            timer["elapsed_before"] = 0.0
            timer["laps"] = []
        else:
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
        center.setNotificationCategories_({category})

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
        self._update_size()
        btn = self.status_item.button()
        self.popover.showRelativeToRect_ofView_preferredEdge_(btn.bounds(), btn, NSMinYEdge)
        NSApp.activateIgnoringOtherApps_(True)
        self.input_field.window().makeFirstResponder_(self.input_field)

    def _show_preview_window(self):
        """Show the production content in a normal window for visual QA only."""
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
        save_state(self.presets, self.timers, self._skipped_update, self.settings)

    def _quit(self):
        self._persist()
        NSApp.terminate_(None)

    def applicationWillTerminate_(self, _notification):
        if self._did_finish_launching:
            self._persist()
        manager = NSAppleEventManager.sharedAppleEventManager()
        manager.removeEventHandlerForEventClass_andEventID_(
            int.from_bytes(b"GURL", "big"), int.from_bytes(b"GURL", "big")
        )
        if self._control_server is not None:
            self._control_server.shutdown()
            self._control_server.server_close()
        try:
            CONTROL_SOCKET_PATH.unlink(missing_ok=True)
        except OSError:
            pass


def main():
    if len(sys.argv) > 1 and sys.argv[1] in {"start", "list", "pause", "cancel", "help", "--help", "-h"}:
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
