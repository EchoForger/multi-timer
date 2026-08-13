# MultiTimer 原生 Swift 版本迭代与发布工作流

> 给维护者和后续 Codex 使用。默认在仓库根目录执行。只有用户明确要求提交、推送或发布时，才执行 GitHub Release 与 Homebrew 外部写操作。

## 1. 发布原则

- [ ] 完整计时界面始终位于 `NSStatusItem + NSPopover`；不要改成普通常驻窗口。
- [ ] `LSUIElement=true`，正常运行时不显示 Dock 图标。
- [ ] 统计、设置和权限窗口按需打开；所有窗口关闭后恢复 `.accessory`，菜单栏项目继续存在。
- [ ] 状态路径保持 `~/.config/multitimer/state.json` 与 `pomodoro-stats.json`，旧 JSON schema 必须可迁移。
- [ ] 官网只展示 DMG 与 Homebrew；README 可在后半部分提供源码构建。
- [ ] 软件、图标、README、官网和截图使用同一套原生 macOS 设计语言。
- [ ] 控件、强调色、深浅模式和文字大小跟随系统。
- [ ] Release、App、DMG、校验文件与 Homebrew cask 版本完全一致。
- [ ] 除非用户明确要求，不升级本机安装版，便于测试旧版检查更新。
- [ ] 不提交 `.build/`、`build/`、`dist/` 或预览状态文件。

## 2. 确认需求和版本

```bash
rg -n '^\s*- \[x\]' ROADMAP.md FEATURE_TODO.md
git status --short
git diff --stat
```

版本必须同步修改：

- [ ] `Support/Info.plist` 的 `CFBundleShortVersionString` 与 `CFBundleVersion`。
- [ ] `MultiTimer/MultiTimerApp.swift` 中关于面板和更新检查的当前版本。
- [ ] `scripts/package.sh` 的 `MULTITIMER_VERSION`。
- [ ] Release Notes 与 Homebrew cask。

```bash
rg -n '0\.8\.0|CFBundleShortVersionString|CFBundleVersion|MULTITIMER_VERSION' \
  Support MultiTimer Scripts
```

## 3. 技术结构

- `MultiTimerCore/`：可测试的数据模型、旧状态迁移、格式化、解析、原子 JSON 与控制协议。
- `MultiTimer/`：SwiftUI 界面与 AppKit 生命周期、菜单栏、Popover、通知、权限、更新、iCloud KVS。
- `MultiTimerCLI/`：`multitimer` 命令，通过本地 Unix Socket 控制运行实例。
- `Tests/MultiTimerCoreTests/`：Swift XCTest。
- `Support/`：App `Info.plist` 与 entitlements。
- `scripts/build.sh`：按 TomatoBar 的方式用 SwiftPM 和 macOS SDK 组装 `.app`。
- `scripts/package.sh`：生成 DMG 与 SHA-256。

SwiftPM 内部 GUI 产物叫 `MultiTimer`，CLI 产物必须叫 `MultiTimerCLI`。不要把两个 product 命名成只存在大小写差异的 `MultiTimer` / `multitimer`；默认 macOS 文件系统会让它们互相覆盖，导致 App 启动成 CLI 后立即退出。打包时再把 `MultiTimerCLI` 安装为 `Contents/Resources/bin/multitimer`。

## 4. 功能兼容检查

### 普通计时器

- [ ] 多个倒计时和秒表可并行运行。
- [ ] 分钟、`MM:SS`、`HH:MM:SS` 与目标时刻解析正确，最大 24 小时。
- [ ] 暂停/继续、取消、完成、重新计时、复制、置顶与调整剩余时间正常。
- [ ] 秒表计圈正常。
- [ ] 双击和 Force Touch 都可行内改名。
- [ ] 菜单栏最近剩余时间使用等宽 `HH:MM`，不显示秒。

### 番茄钟与统计

- [ ] 工作/休息、暂停、跳过、停止、延长 5 分钟与自动循环正常。
- [ ] 只统计自然完成的工作阶段。
- [ ] 每日 24 小时时间线、周/月趋势、热力图、目标、连续达成、徽章、CSV/JSON 导出与清空确认正常。
- [ ] 工作和休息通知使用不同声音。

### 系统集成

- [ ] 登录时启动使用 `LaunchAtLogin`。
- [ ] `⌘⇧⌥M` 和 `multitimer permissions` 都能打开权限窗口。
- [ ] `multitimer://start?name=Tea&minutes=5` 与番茄 URL 正常。
- [ ] CLI 的 `start/list/pause/cancel/permissions/pomodoro` 正常。
- [ ] 设置即时保存，无保存/取消按钮；语言按钮打开 macOS 语言设置。
- [ ] iCloud entitlement 存在时只同步轻量设置；专注历史始终保存在本机，ad-hoc 构建安全回退本地。

### 更新

- [ ] 始终通过 GitHub Releases 判断最新版，不依赖容易触发 403 的未认证 REST API。
- [ ] 更新提示显示 Release Notes 和“立即更新 / 稍后提醒 / 跳过此版本”。
- [ ] Homebrew 来源后台运行 `brew upgrade --cask echoforger/tap/multi-timer`。
- [ ] DMG 来源下载 DMG 与 `.sha256`，校验 Bundle ID 和 SHA-256 后替换 App；失败时恢复备份。

## 5. 源码验证

```bash
swift test
git diff --check
plutil -lint Support/Info.plist Support/MultiTimer.entitlements
```

受限或离线环境可复用已有依赖缓存：

```bash
MULTITIMER_DISABLE_SWIFTPM_SANDBOX=1 \
MULTITIMER_OFFLINE=1 \
./scripts/build.sh debug
```

- [ ] 所有 XCTest 通过。
- [ ] 无编译错误和非预期警告。
- [ ] 旧 schema 迁移、时长解析、版本比较和原子写入测试通过。
- [ ] `git diff --check` 通过。

## 6. 视觉快照

使用独立临时状态，不触碰真实配置：

```bash
open -n -g \
  --env MULTITIMER_PREVIEW=1 \
  --env MULTITIMER_APPEARANCE=light \
  --env MULTITIMER_SNAPSHOT_PATH=/private/tmp/multitimer-light.png \
  --env MULTITIMER_STATE_PATH=/private/tmp/multitimer-light-state.json \
  --env MULTITIMER_STATS_PATH=/private/tmp/multitimer-light-stats.json \
  --env MULTITIMER_SOCKET_PATH=/private/tmp/multitimer-light.sock \
  build/MultiTimer.app
```

深色把 `light` 改为 `dark` 并改输出路径。确认后同步为 `light.png`、`dark.png`。

- [ ] 两张图都是 720 × 1280（2×，逻辑尺寸 360 × 640）。
- [ ] 不拉伸；README 只指定宽度，官网 `316 × 562`。
- [ ] 快捷按钮完整显示，卡片宽度一致，长名称不挤压时间。
- [ ] 深浅色仅外观不同，所有内容一致。

## 7. App 包构建与冒烟测试

```bash
./scripts/build.sh release
codesign --verify --deep --strict build/MultiTimer.app
plutil -p build/MultiTimer.app/Contents/Info.plist
file build/MultiTimer.app/Contents/MacOS/MultiTimer
file build/MultiTimer.app/Contents/Resources/bin/multitimer
```

必须确认：

- [ ] Bundle ID 是 `io.github.echoforger.multitimer`。
- [ ] `LSUIElement=true`，版本号正确，URL Scheme 是 `multitimer`。
- [ ] GUI 与 CLI 是两个不同 Mach-O；GUI 不会输出 CLI Usage 后退出。
- [ ] LaunchAtLogin helper 已嵌入并签名。
- [ ] App 签名结构通过验证。

用隔离状态启动：

```bash
open -n -g \
  --env MULTITIMER_STATE_PATH=/private/tmp/multitimer-smoke-state.json \
  --env MULTITIMER_STATS_PATH=/private/tmp/multitimer-smoke-stats.json \
  --env MULTITIMER_SOCKET_PATH=/private/tmp/multitimer-smoke.sock \
  build/MultiTimer.app

MULTITIMER_SOCKET_PATH=/private/tmp/multitimer-smoke.sock \
  build/MultiTimer.app/Contents/Resources/bin/multitimer start Tea 5

MULTITIMER_SOCKET_PATH=/private/tmp/multitimer-smoke.sock \
  build/MultiTimer.app/Contents/Resources/bin/multitimer list
```

- [ ] 进程持续驻留且菜单栏图标可见。
- [ ] Popover 可开关，普通计时器、番茄钟和秒表可操作。
- [ ] 默认无 Dock 图标；设置和统计在菜单栏面板内切换，关闭后再次打开回到主页。
- [ ] CLI 和 URL Scheme 创建的任务出现在同一实例。
- [ ] 测试结束只终止工作区测试实例，不误杀安装版。

## 8. README 与官网

README：

- [ ] 首先写 DMG 和 Homebrew 安装。
- [ ] 截图用 `<picture>` 随浏览器深浅切换。
- [ ] 后半部分写 Swift 源码运行、测试与打包。
- [ ] 数据路径、CLI、URL Scheme、最低 macOS 版本准确。

官网：

- [ ] 只提供 DMG 和 Homebrew，不提供源码安装入口。
- [ ] 中文 `/multi-timer/` 与英文 `/multi-timer/en/` 内容同步。
- [ ] 首访跟随浏览器语言，手动选择后记住。
- [ ] 下载按钮指向 `releases/latest`。
- [ ] Homebrew 命令是：

```bash
brew tap EchoForger/tap
brew install --cask multi-timer
```

- [ ] 锚点滚动不在固定导航下方留下多余空白。
- [ ] 深浅模式、图标和截图均为当前版本。

## 9. 生成 DMG

```bash
./scripts/package.sh
hdiutil verify dist/MultiTimer-0.7.1.dmg
(cd dist && shasum -a 256 -c MultiTimer-0.7.1.dmg.sha256)
```

- [ ] DMG 中包含 `MultiTimer.app` 与 `/Applications` 快捷方式。
- [ ] App 内版本、Bundle ID 与签名结构正确。
- [ ] SHA-256 校验通过并记录给 Homebrew。

## 10. 提交、推送与 GitHub Release

```bash
git status --short
git diff --check
swift test
git add README.md RELEASE_WORKFLOW.md ROADMAP.md FEATURE_TODO.md \
  Package.swift Package.resolved MultiTimer MultiTimerCore MultiTimerCLI \
  Support scripts Tests assets index.html en/index.html styles.css script.js \
  light.png dark.png .gitignore
git commit -m "feat: release MultiTimer 0.7.1"
git push origin master
```

创建 Release：

```bash
gh release create v0.7.1 \
  dist/MultiTimer-0.7.1.dmg \
  dist/MultiTimer-0.7.1.dmg.sha256 \
  --repo EchoForger/multi-timer \
  --target master \
  --title "MultiTimer 0.7.1" \
  --notes-file /private/tmp/multitimer-0.7.1-notes.md
```

Release Notes 至少说明：原生 Swift 重构、数据兼容、菜单栏可靠性、原生 UI、CLI/URL、通知/更新、最低系统版本和未公证提示。

## 11. Homebrew Tap

仓库：`EchoForger/homebrew-tap`。

`Casks/multi-timer.rb` 必须：

- [ ] `version "0.7.1"`。
- [ ] `sha256` 使用公开 DMG 的真实值。
- [ ] URL 指向 `v#{version}/MultiTimer-#{version}.dmg`。
- [ ] 保留 `app "MultiTimer.app"`。
- [ ] CLI 改为：

```ruby
binary "#{appdir}/MultiTimer.app/Contents/Resources/bin/multitimer", target: "multitimer"
```

验证并推送：

```bash
brew style Casks/multi-timer.rb
git add Casks/multi-timer.rb README.md
git commit -m "chore: update multi-timer to 0.7.1"
git push origin main

brew update
brew info --cask echoforger/tap/multi-timer
brew audit --cask --strict echoforger/tap/multi-timer
brew fetch --cask --force echoforger/tap/multi-timer
```

除非用户明确要求，不执行本机 `brew upgrade`。

## 12. 最终交付

- [ ] Swift 测试、App 构建、签名、菜单栏、Popover、CLI、URL 与通知冒烟测试通过。
- [ ] DMG 与 SHA-256 公开且可下载。
- [ ] 主仓库提交推送，GitHub Release 已发布。
- [ ] Homebrew cask 推送并通过下载校验。
- [ ] GitHub Pages 已显示 0.7.1 的原生截图和正确安装方式。
- [ ] 未留下预览实例或测试状态干扰用户。
- [ ] 最终回复包含版本、提交、Release、官网、Homebrew 和验证结果。
