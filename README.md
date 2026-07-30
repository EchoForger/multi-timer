# MultiTimer

macOS 菜单栏多路倒计时小工具。常驻顶部菜单栏，点击图标弹出小面板；输入任务名、点一个预设时间即可开一个倒计时，可同时跑多个；到点发送**静音**的 macOS 通知提醒你。

## 特性

- 常驻 macOS 菜单栏（顶部工具栏），点击图标弹出小面板，**不在 Dock 显示**
- 无边框悬浮面板，小巧精致，点击别处自动收起
- 输入 label + 点击预设时间即开始，可并行多个倒计时
- 预设（1min / 5min …）可自行增删改，本地持久化
- 任务名留空自动命名（`任务-HHMMSS`）
- 每个倒计时带进度条，最后 10 秒变红
- 到点发送 macOS 通知（`osascript`，无声音）
- 预设与运行中的倒计时状态本地保存，重开自动恢复
- 倒计时结束后自动从列表移除

## 打包成 macOS App（推荐，双击即用，无需终端）

```bash
pip install pyinstaller
pyinstaller MultiTimer.spec --noconfirm --clean
```

产物在 `dist/MultiTimer.app`。把它拖进「应用程序」即可：

```bash
cp -R dist/MultiTimer.app /Applications/
open /Applications/MultiTimer.app
```

启动后图标出现在右上角菜单栏，Dock 里不显示（`Info.plist` 里 `LSUIElement=1`）。
想开机自启：系统设置 → 通用 → 登录项 → 添加 MultiTimer.app。

## 作为命令行/pip 包使用

```bash
pip install .
multitimer          # 或不安装: python3 multitimer.py
```

## 说明

- 通知依赖 macOS 的 `osascript`，仅在 macOS 下生效。
- 配置文件位于 `~/.config/multitimer/state.json`。
