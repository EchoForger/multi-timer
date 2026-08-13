<div align="center">

<img src="assets/app-icon.png" width="112" alt="MultiTimer 图标">

# MultiTimer

**多个倒计时，一个节奏。**

一款轻巧、原生的多设备计时器：Mac 菜单栏、iPhone、Widget 与 Live Activity，内置完整番茄循环和专注时间线。

[![Latest Release](https://img.shields.io/github/v/release/EchoForger/multi-timer?style=flat-square&label=release&color=007AFF)](https://github.com/EchoForger/multi-timer/releases/latest)
[![macOS](https://img.shields.io/badge/macOS-Ventura%2B-1D1D1F?style=flat-square&logo=apple&logoColor=F5F5F7)](https://www.apple.com/macos/)
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
3. 启动 MultiTimer，计时器图标会出现在菜单栏，不占用 Dock。

### Homebrew

```bash
brew tap EchoForger/tap
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

1. 点击菜单栏中的计时器图标，完整计时界面会在图标下方展开。
2. 输入任务名，或留空自动命名。
3. 用先慢后快的指数拉杆选择 0 到 24 小时的时长；界面会同步显示 `HH:MM:SS` 和预计响铃时刻。
4. 双击计时名称，或在 Force Touch 触控板上用力按压，可行内改名；点击文本框外会自动保存。
5. 运行中可以暂停、复制和置顶，列表可按最近到期自动排序。
6. 点击“秒表”开始正向计时，并使用“计圈”记录圈次。
7. 时间到后，选择“重新计时”或“已检查”。

### 倒计时预设

常用倒计时可以保存为预设，并设置名称、时长、系统语义色、系统声音或静音，以及提前 1/5/10 分钟提醒。预设数量不限，支持搜索和拖动排序；最多收藏四个，收藏会显示在 Mac 主面板和 iPhone Widget，点击一次立即开始。秒表和番茄钟不会混入预设列表。

### 番茄钟

番茄钟位于普通计时器列表之外，默认工作 25 分钟、短休息 5 分钟、长休息 15 分钟，每完成 4 个番茄钟进入长休息。四项参数均可调整；只有自然完成的工作阶段增加轮次，跳过或中断仍保留实际专注时长但不增加完整轮次。开启自动循环后，休息结束自动开始下一轮工作。菜单栏同时显示番茄钟和普通倒计时：专注状态使用红色胶囊，休息状态使用绿色胶囊，普通倒计时保持系统样式。

番茄钟卡片显示今日专注进度、专注次数和完整番茄钟数。点击番茄钟旁的统计图标，可在同一个菜单栏面板中查看每天的 24 小时专注时间线，以及自然周、自然月的专注趋势和番茄钟热力图。每日目标支持 15–480 分钟，连续达成天数与 10–1000 小时里程碑均从原始记录实时计算。运行中的番茄阶段会在重启后恢复，暂停时间不会计入有效专注时长。

统计记录可导出为 CSV，或导出完整 JSON 备份。手动停止和跳过的实际专注时长会计入每日目标，但只有自然完成的工作阶段才算完整番茄钟。旧版本记录会继续保留，并明确标记为由开始、结束时间估算的时长。

点击右上角的齿轮可在同一个面板中设置登录时启动、菜单栏剩余时间/数量、最近到期排序、番茄工作/休息时长、自动循环和是否显示番茄模块。专注与休息时长使用分钟滑杆，所有修改立即保存。语言由 macOS“语言与地区”中的应用语言统一管理，设置页提供系统入口。

权限窗口统一显示菜单栏、通知和登录时启动三项状态。即使菜单栏图标不可见，也可以按全局快捷键 `⌘⇧⌥M`，或在终端运行 `multitimer permissions` 打开该窗口。

## 关于与更新

MultiTimer 每次启动都会通过 GitHub Release 检查最新版。发现新版时会显示 Release 新版特性，并提供“立即更新”“晚点提醒我”和“跳过这个版本”。面板底部提供“关于”和“检查更新”，可查看当前版本、EchoForger 版权与许可信息，也可手动检查更新。

- Homebrew 安装：确认立即更新后，MultiTimer 在后台通过 Homebrew 更新，完成后提示重启。
- DMG 安装：确认立即更新后，自动下载、校验 SHA256 并替换应用，完成后提示重启。

## 特性

- 不限数量的倒计时预设：搜索、排序、四收藏、颜色、声音与提前提醒
- 完整番茄循环：短休息、长休息、轮次与可选自动循环
- 原生 iPhone 双标签界面、收藏预设 Widget、当前计时器 Widget 与 Live Activity
- Live Activity 最近操作自动选择、手动固定，以及暂停、继续、延长和结束确认
- CloudKit 私有数据库与 `CKSyncEngine` 同步预设、活跃计时器和设置；支持离线队列、幂等操作、冲突修订与删除墓碑
- 番茄钟彩色菜单栏胶囊与普通倒计时同时显示，并为工作/休息使用不同提示音
- 精确扣除暂停时间的每日 24 小时专注时间线
- 自然周/月趋势、番茄钟热力图和中性的上一周期对比
- 15–480 分钟每日目标、连续达成天数与累计专注徽章墙
- CSV 分析导出、完整 JSON 备份和兼容旧统计记录的数据迁移
- 番茄钟 CLI、URL Scheme 和通知“延长 5 分钟”操作
- 同时运行多个倒计时
- 菜单栏完整计时面板：创建、编辑和管理所有倒计时、秒表与番茄钟
- 内嵌专注统计与设置页面，关闭面板后再次打开会回到计时器主页
- 秒表模式与圈次记录
- 暂停、复制、置顶和最近到期排序
- 先慢后快的指数时长拉杆，精细选择短时长并快速扩展到 24 小时
- 创建区实时显示 `HH:MM:SS` 与预计响铃时间
- 可选在菜单栏用等宽 `HH:MM` 显示最近剩余时间（不显示秒）与运行数量
- 原生登录项与通知权限诊断
- 双击或 Force Touch 原生行内改名
- 原生关于面板与安装来源感知更新
- macOS 原生到时通知
- 自动跟随系统深浅主题
- 跟随 macOS 系统或应用语言设置，支持简体中文与英文
- 按钮和计时颜色跟随系统强调色
- 原子保存未结束的任务和设置，并兼容旧版状态文件
- 启动后自动展开主面板；收回后仅驻留菜单栏，不显示 Dock 图标
- 无账户、无遥测；默认仅使用本地数据
- 具备 Apple CloudKit entitlement 的签名构建可同步预设、活跃计时器和轻量设置；持续增长的专注历史始终留在每台设备本机

Mac 普通状态保存在 `~/.config/multitimer/state.json`，番茄钟记录保存在 `~/.config/multitimer/pomodoro-stats.json`。iPhone 与 Widget 使用 App Group 中的共享状态文件。每条专注记录包含开始/结束时间、有效专注秒数、完成状态、记录时区和不含任务内容的专注片段；目标、趋势、连续天数与徽章均实时派生，不保存任务名，不发送遥测。历史默认永久保存在本机；没有 iCloud entitlement 时会安全使用本地存储。

## 自动化

启动一个名为 Tea 的 5 分钟倒计时：

```text
multitimer://start?name=Tea&minutes=5
```

通过 Homebrew 或源码安装后，也可使用命令行控制正在运行的应用实例：

```bash
multitimer start Tea 5
multitimer start --stopwatch Focus
multitimer list
multitimer pause Tea
multitimer cancel Tea
multitimer permissions

multitimer pomodoro start
multitimer pomodoro status
multitimer pomodoro pause
multitimer pomodoro skip
multitimer pomodoro stop
```

也可以通过 `multitimer://pomodoro/start` 开始番茄工作。CLI 只使用本机 Unix Socket；MultiTimer 不开放本地或局域网 HTTP 端口。

## 开发者

### 从源码运行

需要 macOS 13 或更高版本，以及 Xcode 15+ 或 Swift 5.9+ Command Line Tools：

```bash
git clone https://github.com/EchoForger/multi-timer.git
cd multi-timer

./scripts/run.sh debug
```

### 打包 macOS App

```bash
./scripts/build.sh release
```

构建结果位于 `build/MultiTimer.app`。生成 DMG 与 SHA-256：

```bash
./scripts/package.sh
```

### 构建 iPhone 与 Widget

使用 Xcode 26 打开 `MultiTimer.xcodeproj`，选择 `MultiTimerMobile` scheme。iPhone 首版最低支持 iOS 18。真机、CloudKit、Widget、Live Activity 与 TestFlight 发布前需要完成 [移动端发布检查点](MOBILE_RELEASE_CHECKLIST.md) 中的 Developer Team、Container、App Group 和描述文件配置。

### 参与贡献

运行逻辑测试：

```bash
swift test
```

欢迎提交 [Issue](https://github.com/EchoForger/multi-timer/issues) 和 Pull Request。修改界面时，请同时检查浅色、深色、长任务名以及计时结束状态。

## 许可证

MultiTimer 使用 Swift、SwiftUI、AppKit 和原生 macOS SDK 构建，工程结构与菜单栏生命周期参考 [TomatoBar](https://github.com/ivoronin/TomatoBar)，基于 [MIT License](LICENSE) 开源。
