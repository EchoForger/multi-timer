# MultiTimer

多路倒计时小工具（macOS）。输入任务名、点一个预设时间即可开一个倒计时，可同时跑多个；到点发送**静音**的 macOS 通知提醒你。

## 特性

- GUI（PySide6），窗口置顶、随时可见，默认贴在桌面右下角
- 输入 label + 点击预设时间即开始，可并行多个倒计时
- 预设（1min / 5min …）可自行增删改，本地持久化
- 任务名留空自动命名（`任务-HHMMSS`）
- 每个倒计时带进度条，最后 10 秒变红
- 到点发送 macOS 通知（`osascript`，无声音）
- 预设与运行中的倒计时状态本地保存，重开自动恢复
- 倒计时结束后自动从列表移除

## 安装

```bash
pip install .
```

## 使用

安装后直接运行命令：

```bash
multitimer
```

或不安装直接跑脚本：

```bash
python3 multitimer.py
```

## 说明

- 通知依赖 macOS 的 `osascript`，仅在 macOS 下生效。
- 配置文件位于 `~/.config/multitimer/state.json`。
