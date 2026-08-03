<div align="center">

<img src="assets/app-icon.png" width="112" alt="MultiTimer 图标">

# MultiTimer

**多个倒计时，一个节奏。**

一款轻巧、原生的 macOS 菜单栏多任务倒计时器。

[![Latest Release](https://img.shields.io/github/v/release/EchoForger/multi-timer?style=flat-square&label=release&color=007AFF)](https://github.com/EchoForger/multi-timer/releases/latest)
[![macOS](https://img.shields.io/badge/macOS-Big%20Sur%2B-1D1D1F?style=flat-square&logo=apple&logoColor=F5F5F7)](https://www.apple.com/macos/)
[![License](https://img.shields.io/badge/license-MIT-34C759?style=flat-square&labelColor=1D1D1F&color=34C759)](LICENSE)
[![Website](https://img.shields.io/badge/website-MultiTimer-007AFF?style=flat-square)](https://echoforger.github.io/multi-timer/)

<p>
  <a href="https://github.com/EchoForger/multi-timer/releases/latest">
    <img src="https://img.shields.io/badge/_下载_macOS_版-1D1D1F?style=for-the-badge&logoColor=F5F5F7" alt="下载最新的 macOS 版本">
  </a>
</p>

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="dark.png">
  <source media="(prefers-color-scheme: light)" srcset="light.png">
  <img src="light.png" alt="MultiTimer 紧凑的原生 macOS 界面" width="316">
</picture>

</div>

## 安装

### 下载 DMG

前往 [Latest Release](https://github.com/EchoForger/multi-timer/releases/latest) 下载 `MultiTimer-<版本号>.dmg`：

1. 打开 DMG。
2. 将 `MultiTimer.app` 拖入“应用程序”文件夹。
3. 启动 MultiTimer，计时器图标会出现在菜单栏。

### Homebrew

```bash
brew tap EchoForger/multi-timer
brew install --cask multi-timer
```

更新到最新版：

```bash
brew update
brew upgrade --cask multi-timer
```

卸载：

```bash
brew uninstall --cask multi-timer
```

### 首次打开

当前版本尚未经 Apple 签名和公证。如果 macOS 阻止启动：

1. 在 Finder 的“应用程序”中找到 `MultiTimer.app`。
2. 右键应用，选择“打开”。
3. 在确认窗口中再次点击“打开”。

首次启动时请允许 MultiTimer 发送通知，否则计时结束时无法显示提醒。

## 怎么用

1. 点击菜单栏中的计时器图标。
2. 输入任务名，或留空自动命名。
3. 点击预设时长，或输入自定义分钟数。
4. 双击计时名称，或在 Force Touch 触控板上用力按压，可直接行内改名。
5. 运行中可以延长 1、10、60 分钟，也可随时取消。
6. 时间到后，选择“重新计时”或“已检查”。

## 关于与更新

MultiTimer 每次启动都会通过 GitHub Release 检查最新版。发现新版时会显示 Release 新版特性，并提供“立即更新”“晚点提醒我”和“跳过这个版本”。点击面板右上角的 `ⓘ` 打开“关于 MultiTimer”，可查看当前版本、安装来源、EchoForger 版权与许可信息，也可手动检查更新。

- Homebrew 安装：确认立即更新后，MultiTimer 在后台通过 Homebrew 更新，完成后提示重启。
- DMG 安装：确认立即更新后，自动下载、校验 SHA256 并替换应用，完成后提示重启。
- 源码运行：不会覆盖开发目录，只会引导到 GitHub Release 页。

## 特性

- 同时运行多个倒计时
- 双击或 Force Touch 原生行内改名
- 原生关于面板与安装来源感知更新
- 自定义快捷时间预设
- macOS 原生到时通知
- 自动跟随系统深浅主题
- 按钮、进度和计时颜色跟随系统强调色
- 自动保存预设和未结束的任务
- 只驻留菜单栏，不占用 Dock
- 无账户、无遥测，数据仅保存在本机

本地状态保存在 `~/.config/multitimer/state.json`。

## 开发者

### 从源码运行

需要 macOS 和 Python 3.9 或更高版本：

```bash
git clone https://github.com/EchoForger/multi-timer.git
cd multi-timer

python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .

multitimer
```

### 打包 macOS App

```bash
python3 -m pip install pyinstaller
pyinstaller MultiTimer.spec --noconfirm --clean
```

构建结果位于 `dist/MultiTimer.app`。

### 参与贡献

欢迎提交 [Issue](https://github.com/EchoForger/multi-timer/issues) 和 Pull Request。修改界面时，请同时检查浅色、深色、长任务名以及计时结束状态。

## 许可证

MultiTimer 使用 Python、PyObjC 和 AppKit 构建，基于 [MIT License](LICENSE) 开源。
