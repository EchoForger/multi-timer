# MultiTimer 版本迭代与发布工作流

> 给后续维护者和 Codex 使用的可执行发布手册。默认从仓库根目录运行命令。
>
> 发布是外部写操作：只有用户明确要求“提交、推送或发布新版本”时，才执行 GitHub Release、Homebrew 推送等步骤。

## 0. 发布原则

- [ ] MultiTimer 始终是纯菜单栏应用，`LSUIElement` 必须为 `true`，不得在 Dock 中显示常驻图标。
- [ ] 不覆盖用户已有计时器、设置或预设；状态文件迁移必须向后兼容。
- [ ] 官网只展示 DMG 和 Homebrew 两种安装方式，不写源码安装。
- [ ] README 先写 DMG 和 Homebrew 安装，再写使用说明、自动化与开发者内容。
- [ ] 软件、README、官网、图标和截图保持同一套设计语言。
- [ ] 浅色、深色和按钮颜色跟随 macOS；不要写死强调色。
- [ ] Release、源码、应用包、DMG、校验文件和 Homebrew cask 必须使用同一个版本号。
- [ ] 不自动升级本机旧版本，除非用户明确要求；保留旧版本便于测试检查更新流程。
- [ ] 不提交 `build/`、`dist/`、缓存或临时测试状态。

## 1. 确认本次需求范围

- [ ] 查看 `ROADMAP.md` 中用户勾选的所有 `- [x]` 项。
- [ ] 将勾选项分成系统集成、计时器、菜单栏、自动化、文档与发布几组。
- [ ] 确认每个勾选项都有明确的实现位置和验证方法。
- [ ] 检查工作区，保留用户已有修改，不覆盖无关文件。

```bash
rg -n '^\s*- \[x\]' ROADMAP.md
git status --short
git log -1 --oneline
```

如果需求跨度较大，先在工作计划中分阶段：

1. 状态与系统集成。
2. 核心计时能力和 UI。
3. URL Scheme、CLI 与本地通信。
4. 测试、文档和构建。
5. GitHub Release 与 Homebrew。

## 2. 选择版本号

遵循语义化版本：

- 修复且不改变功能：补丁版本，例如 `0.4.0 → 0.4.1`。
- 新增向后兼容功能：次版本，例如 `0.4.1 → 0.5.0`。
- 不兼容的数据或接口变化：主版本。

设置本次版本变量，后续命令统一引用：

```bash
release_version="0.6.0"
```

必须同步修改：

- [ ] `multitimer.py` 中的 `APP_VERSION`。
- [ ] `MultiTimer.spec` 中的 `CFBundleShortVersionString`。
- [ ] `MultiTimer.spec` 中的 `CFBundleVersion`。
- [ ] `pyproject.toml` 中的项目版本。

检查是否残留旧版本：

```bash
rg -n 'APP_VERSION|CFBundleShortVersionString|CFBundleVersion|^version =' \
  multitimer.py MultiTimer.spec pyproject.toml
```

## 3. 实现与兼容性要求

### 状态文件

- [ ] 配置位置保持为 `~/.config/multitimer/state.json`。
- [ ] 新字段提供默认值，旧状态文件能够直接读取。
- [ ] 持久化数据中不要混入 AppKit 控件或运行时对象。
- [ ] 新计时器类型、暂停、置顶、圈次等状态重启后仍能恢复。

### 菜单栏与 UI

- [ ] `MultiTimer.spec` 保留 `'LSUIElement': True`。
- [ ] 正常启动使用 `NSApplicationActivationPolicyAccessory`。
- [ ] 设置入口仍从 Popover 打开，不创建独立常驻窗口。
- [ ] 正式版状态栏项目使用稳定且唯一的 `autosaveName`；开发版使用不同名称，避免共享 Control Center 状态。
- [ ] 控件优先使用 AppKit 原生控件和 SF Symbols。
- [ ] 卡片宽度一致，按钮不被压缩或截断。
- [ ] 分别检查没有计时器、多个倒计时、秒表、暂停、完成和长名称。
- [ ] 菜单栏标题、图标位置和宽度只在内容变化时更新，不得在每次 ticker 中无条件重设。
- [ ] 菜单栏剩余时间使用等宽 `HH:MM`，不显示秒，避免数字变化时左右抖动。
- [ ] 偏好设置位于 Popover 内，开关即时保存，不出现统一的“保存/取消”按钮。
- [ ] 应用语言由 macOS“语言与地区”管理，偏好设置仅提供系统页面入口。
- [ ] 不同时运行安装版与同 Bundle ID 的 `dist/MultiTimer.app`。

### 自动更新

- [ ] 永远通过 GitHub Release 判断最新版本。
- [ ] 避免依赖 GitHub 未认证 REST API，以免遇到 `403 rate limit exceeded`。
- [ ] 当前实现通过 `/releases/latest` 重定向识别版本，并从 `releases.atom` 读取更新日志。
- [ ] Homebrew 安装来源执行指定 cask 更新命令。
- [ ] DMG 安装来源下载 DMG、读取 `.sha256`、校验并替换应用。
- [ ] 更新前必须由用户选择“立即更新 / 晚点提醒 / 跳过版本”。
- [ ] Homebrew 更新确认中显示将执行的完整命令。

### CLI 与 URL Scheme

- [ ] `MultiTimer.spec` 中保留 `multitimer` URL Scheme。
- [ ] URL 示例可实际创建计时器：

```text
multitimer://start?name=Tea&minutes=5
```

- [ ] CLI 至少验证 `start`、`list`、`pause`、`cancel`。
- [ ] CLI 与菜单栏实例只通过本机 Unix Socket 通信，不开放网络端口。
- [ ] Homebrew cask 保留 Binary stanza：

```ruby
binary "#{appdir}/MultiTimer.app/Contents/MacOS/MultiTimer", target: "multitimer"
```

## 4. 源码验证

每次发布至少执行：

```bash
python -m py_compile multitimer.py
python -m unittest discover -s tests -v
git diff --check
```

检查版本和 URL 解析：

```bash
python - <<'PY'
import multitimer

print(multitimer.APP_VERSION)
print(multitimer._parse_multitimer_url(
    "multitimer://start?name=Tea&minutes=5"
))
PY
```

- [ ] 所有逻辑测试通过。
- [ ] 没有语法错误。
- [ ] `git diff --check` 没有空白错误。
- [ ] 旧配置迁移测试通过。

## 5. 视觉预览和截图

使用独立临时状态文件，避免改动用户真实配置：

```bash
MULTITIMER_PREVIEW=1 \
MULTITIMER_DISABLE_NOTIFICATIONS=1 \
MULTITIMER_STATE_PATH=/private/tmp/multitimer-release-preview.json \
MULTITIMER_APPEARANCE=light \
MULTITIMER_SNAPSHOT_PATH="$PWD/light.png" \
python multitimer.py
```

深色截图把 `MULTITIMER_APPEARANCE` 改为 `dark`，输出为 `dark.png`。

- [ ] `light.png` 与 `dark.png` 内容一致，仅外观不同。
- [ ] 截图包含有代表性的倒计时和秒表。
- [ ] 截图尺寸比例正确，README 和官网不得拉伸图片。
- [ ] 官网 `<img>` 的 `width`、`height` 与图片比例一致。
- [ ] README 使用 `<picture>` 根据浏览器深浅模式切换截图。
- [ ] 检查紧凑布局、长名称、计圈文字、置顶和所有按钮。

预览进程验证完成后要退出，不要留下测试实例。

## 6. 同步 README 与官网

### README

- [ ] 图标、简介、最新 Release 下载按钮正常。
- [ ] 首先写 DMG 安装。
- [ ] 然后写 Homebrew 安装与更新。
- [ ] 更新本版本的功能和使用方法。
- [ ] 自动化部分同步 URL Scheme 与 CLI。
- [ ] 开发者部分保留源码运行、测试和打包说明。
- [ ] 本地状态文件路径准确。

### 官网

- [ ] 只提供“下载 DMG”和“Homebrew 安装”。
- [ ] 不出现源码安装入口。
- [ ] 下载按钮指向 `releases/latest`。
- [ ] Homebrew 命令保持：

```bash
brew tap EchoForger/multi-timer
brew install --cask multi-timer
```

- [ ] 软件特性、图标和截图同步更新。
- [ ] 中文主页位于 `/multi-timer/`，英文主页位于 `/multi-timer/en/`，两种语言的功能和安装说明保持同步。
- [ ] 首次访问根据浏览器语言选择页面，手动切换后记住用户选择。
- [ ] 两个页面都保留正确的 `canonical`、`hreflang`、标题、简介和社交分享信息。
- [ ] 锚点导航后没有多余顶部空白。
- [ ] 网站跟随浏览器深浅模式。

## 7. 构建应用包

```bash
pyinstaller MultiTimer.spec --noconfirm --clean
```

检查产物：

```bash
codesign --verify --deep --strict dist/MultiTimer.app
plutil -p dist/MultiTimer.app/Contents/Info.plist
file dist/MultiTimer.app/Contents/MacOS/MultiTimer
```

- [ ] 版本号正确。
- [ ] `LSUIElement` 为 `true`。
- [ ] Bundle ID 为 `io.github.echoforger.multitimer`。
- [ ] `CFBundleURLTypes` 包含 `multitimer`。
- [ ] 当前构建架构与 Release 说明一致。
- [ ] `codesign --verify` 通过。

当前构建使用 ad-hoc 签名，尚未完成 Apple Developer ID 签名与公证。发布说明和安装文档必须继续保留首次打开提示，直到正式完成 Notarization。

## 8. 应用包冒烟测试

用 LaunchServices 启动打包后的独立测试实例：

```bash
open -n -g \
  --env MULTITIMER_PREVIEW=1 \
  --env MULTITIMER_DISABLE_NOTIFICATIONS=1 \
  --env MULTITIMER_STATE_PATH=/private/tmp/multitimer-bundle-test.json \
  dist/MultiTimer.app
```

不要直接执行 `dist/MultiTimer.app/Contents/MacOS/MultiTimer` 来启动 GUI。macOS 26 可能继承终端或自动化宿主的 XPC 身份，把 MultiTimer 的菜单栏项目错误登记到宿主应用名下并永久隐藏。应用自身也必须检测这种启动方式，并在创建状态栏项前通过 LaunchServices 重新启动。

验证 CLI：

```bash
MULTITIMER_STATE_PATH=/private/tmp/multitimer-bundle-test.json \
dist/MultiTimer.app/Contents/MacOS/MultiTimer start Tea 5

MULTITIMER_STATE_PATH=/private/tmp/multitimer-bundle-test.json \
dist/MultiTimer.app/Contents/MacOS/MultiTimer list
```

验证实际 URL Scheme 时，系统中不能有同 Bundle ID 的旧版实例阻止测试包启动：

1. 先确认并正常退出当前 MultiTimer。
2. 通过 `open` 启动 `dist/MultiTimer.app`。
3. 打开 `multitimer://start?name=URLTest&minutes=3`。
4. 用 CLI `list` 确认 `URLTest` 已创建。
5. 退出测试包。
6. 如测试前旧版正在运行，重新打开旧版。

- [ ] 菜单栏图标出现。
- [ ] Dock 没有 MultiTimer 图标。
- [ ] Unified Log 中没有每 0.5 秒重复发送的 Control Center `SceneFenceAction`。
- [ ] Popover 可以打开和关闭。
- [ ] 创建、暂停、复制、置顶、减时和取消正常。
- [ ] 秒表和计圈正常。
- [ ] URL Scheme 正常。
- [ ] CLI 四个命令正常。
- [ ] 退出后没有测试进程残留。

## 9. 生成与验证 DMG

```bash
release_version="0.6.0"
release_stage=$(mktemp -d /private/tmp/multitimer-dmg.XXXXXX)

ditto dist/MultiTimer.app "$release_stage/MultiTimer.app"
ln -s /Applications "$release_stage/Applications"

hdiutil create \
  -volname MultiTimer \
  -srcfolder "$release_stage" \
  -ov \
  -format UDZO \
  "dist/MultiTimer-${release_version}.dmg"

shasum -a 256 "dist/MultiTimer-${release_version}.dmg" \
  > "dist/MultiTimer-${release_version}.dmg.sha256"
```

验证：

```bash
hdiutil verify "dist/MultiTimer-${release_version}.dmg"
shasum -a 256 -c "dist/MultiTimer-${release_version}.dmg.sha256"
```

还应挂载 DMG，并确认内部应用的版本、Bundle ID 和签名结构与 `dist/MultiTimer.app` 一致。

- [ ] DMG 中存在 `MultiTimer.app`。
- [ ] DMG 中存在指向 `/Applications` 的快捷方式。
- [ ] `hdiutil verify` 通过。
- [ ] SHA-256 校验通过。
- [ ] 记录最终 DMG 的 SHA-256，Homebrew 必须使用这个值。

## 10. 提交与推送主仓库

发布前再次检查范围：

```bash
git status --short
git diff --check
git diff --stat
python -m unittest discover -s tests -v
```

只暂存本次相关文件，不使用 `git add .`：

```bash
git add \
  MultiTimer.spec \
  README.md \
  RELEASE_WORKFLOW.md \
  ROADMAP.md \
  dark.png \
  index.html \
  light.png \
  multitimer.py \
  pyproject.toml \
  tests
```

提交并推送：

```bash
git commit -m "feat: release MultiTimer ${release_version}"
git push origin master
```

- [ ] 工作树在提交后干净。
- [ ] Commit 已推送到 `master`。
- [ ] 不包含 `build/`、`dist/` 或本地缓存。

## 11. 创建 GitHub Release

先确认版本不存在：

```bash
gh release view "v${release_version}" --repo EchoForger/multi-timer
```

创建正式 Release，并上传 DMG 与校验文件：

```bash
gh release create "v${release_version}" \
  "dist/MultiTimer-${release_version}.dmg" \
  "dist/MultiTimer-${release_version}.dmg.sha256" \
  --repo EchoForger/multi-timer \
  --target master \
  --title "MultiTimer ${release_version}" \
  --notes "在这里写完整、面向用户的更新日志"
```

Release Notes 要求：

- [ ] 开头概括版本价值。
- [ ] 逐条覆盖本次已完成需求。
- [ ] 单独列出自动化、更新、UI 与文档变化。
- [ ] 保留未签名、未公证提示。
- [ ] 使用可被 GitHub Atom Feed 正常转换的标题和列表。

验证公开 Release：

```bash
gh release view "v${release_version}" \
  --repo EchoForger/multi-timer \
  --json url,tagName,isDraft,isPrerelease,assets,publishedAt
```

再用应用自身的 `_fetch_latest_release()` 验证它能识别新版本、DMG 名称和完整更新日志。

## 12. 更新 Homebrew Tap

仓库：`EchoForger/homebrew-multi-timer`

在临时目录克隆 tap：

```bash
git clone \
  https://github.com/EchoForger/homebrew-multi-timer.git \
  /private/tmp/homebrew-multi-timer
```

修改 `Casks/multi-timer.rb`：

- [ ] `version` 改为本次版本。
- [ ] `sha256` 使用最终公开 DMG 的真实 SHA-256。
- [ ] URL 仍指向 `v#{version}/MultiTimer-#{version}.dmg`。
- [ ] 保留 `app "MultiTimer.app"`。
- [ ] 保留 `binary` stanza，让 `multitimer` 命令进入 Homebrew `bin`。
- [ ] 保留 Gatekeeper caveats 和 zap 路径。

格式检查：

```bash
brew style /private/tmp/homebrew-multi-timer/Casks/multi-timer.rb
```

提交和推送 tap：

```bash
cd /private/tmp/homebrew-multi-timer
git add Casks/multi-timer.rb
git commit -m "chore: update multi-timer to ${release_version}"
git push origin main
```

回到主仓库后刷新并验证公开 cask：

```bash
brew update
brew info --cask echoforger/multi-timer/multi-timer
brew audit --cask --strict echoforger/multi-timer/multi-timer
brew fetch --cask --force echoforger/multi-timer/multi-timer
```

- [ ] `brew info` 显示新版本。
- [ ] Artifacts 同时显示 App 和 `multitimer` Binary。
- [ ] `brew audit` 通过。
- [ ] `brew fetch` 下载并校验成功。
- [ ] 除非用户要求，不执行本机 `brew upgrade`。

## 13. 验证 GitHub Pages

官网由主仓库 GitHub Pages 部署到：

`https://echoforger.github.io/multi-timer/`

确认新版内容已经公开：

```bash
curl -fsSL https://echoforger.github.io/multi-timer/ \
  | rg '本版本新增的官网关键词'
```

- [ ] 首页显示新版功能文字。
- [ ] 中文和英文页面都可访问，语言按钮能双向切换。
- [ ] 浅色和深色截图是新版。
- [ ] 下载按钮进入最新 Release。
- [ ] Homebrew 命令准确。
- [ ] 页面没有源码安装入口。

## 14. 保留旧版测试自动更新

如果要测试 `旧版本 → 新版本`：

- [ ] 发布新版本前确认本机安装的是旧版本。
- [ ] 不运行 `brew upgrade`，也不替换 `/Applications/MultiTimer.app`。
- [ ] 新版本发布完成后，退出并重新打开旧版，触发启动检查。
- [ ] 或在 `ⓘ → 检查更新` 中手动触发。
- [ ] 验证版本号、完整更新日志以及三个选择按钮。
- [ ] Homebrew 来源应后台执行指定 cask 更新。
- [ ] DMG 来源应下载、校验并替换应用。

注意：更新确认界面由“当前正在运行的旧版本”提供。某个版本新加入的更新 UI，只能在它升级到下一版本时完整测试。若要专门验证新版更新器，需要再发布一个测试补丁版本，或使用本地模拟 Release。

## 15. 最终交付清单

- [ ] 所有用户勾选需求已经实现。
- [ ] 单元测试、语法检查、UI 预览和应用包冒烟测试通过。
- [ ] `MultiTimer.app` 版本与元数据正确。
- [ ] DMG 与 SHA-256 已验证。
- [ ] 主仓库已提交并推送。
- [ ] GitHub Release 已公开，更新日志可被应用读取。
- [ ] Homebrew cask 已推送、审计和下载验证通过。
- [ ] 官网已部署新版文字与截图。
- [ ] 本机是否升级符合用户要求。
- [ ] 没有残留测试进程。
- [ ] 最终回复包含版本号、Release、官网、Homebrew、提交号和验证结果。

## 常见问题

### 检查更新出现 GitHub 403

不要切回未认证 REST API。优先检查 `/releases/latest` 重定向和 `releases.atom` 是否可访问。

### `brew upgrade` 提示已经是最新版

依次确认：

1. GitHub Release 已公开，不是 Draft。
2. Homebrew tap 中的版本和 SHA 已推送。
3. 已运行 `brew update`。
4. `brew info --cask echoforger/multi-timer/multi-timer` 显示新版本。

### 菜单栏图标不显示

1. 确认没有同 Bundle ID 的重复进程。
2. 确认 `LSUIElement=true` 且使用 Accessory activation policy。
3. 确认正式版使用稳定的 status item `autosaveName`，开发版使用独立名称；不要移除明确标识，也不要让两个环境复用同一个标识。
4. 检查“系统设置 → 菜单栏 → 允许在菜单栏中”中的 MultiTimer 开关。
5. 使用应用内状态栏自检和“重新创建图标”。

如果日志出现 `Created ephemeral instance`、`Moving host to blocked list` 和 `hiding status items`，优先检查状态栏项目是否缺少稳定 `autosaveName`。正式版必须使用稳定标识，开发版应使用另一个稳定标识。

如果日志出现 `Adding menu item at .bundle(MultiTimer) to tracked application at .bundle(另一个应用)`，说明打包应用被直接执行并继承了父应用的 XPC 身份。GUI 必须通过 LaunchServices 启动；CLI 子命令仍可直接执行二进制。

每 0.5 秒出现 Control Center `SceneFenceAction` 不一定来自状态栏标题；Popover 关闭时更新隐藏的计时器控件也会触发场景提交。关闭面板时只更新计时逻辑和菜单栏摘要，重新打开面板前再刷新行内容。

### URL Scheme 测试没有创建计时器

通常是旧版同 Bundle ID 进程仍在运行，导致测试包的单实例保护直接退出。正常退出旧版、启动测试包，再发送 URL；测试后恢复旧版。

### PyInstaller 清理缓存时报权限错误

PyInstaller 的用户缓存位于 `~/Library/Application Support/pyinstaller`。在受限环境中需要获得权限后重新执行同一个构建命令，不要绕过缓存或改写用户目录。
