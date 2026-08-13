# MultiTimer 0.9.0 移动端发布检查点

- [ ] 在 Xcode 中设置 Apple Developer Team。
- [ ] 在开发者后台创建并分配 `iCloud.io.github.echoforger.multitimer` CloudKit Container。
- [ ] 注册 App Group：`group.io.github.echoforger.multitimer`。
- [ ] 注册 iOS Bundle ID：`io.github.echoforger.multitimer.ios`。
- [ ] 注册 Widget Bundle ID：`io.github.echoforger.multitimer.ios.widgets`。
- [ ] 创建 iOS App、Widget、CloudKit、App Group 与推送通知描述文件。
- [ ] 为 Mac 配置 Developer ID Application、CloudKit entitlement 和公证凭据。
- [ ] 在 Xcode 安装与当前 SDK 匹配的 iOS Simulator Runtime。
- [ ] 在 CloudKit Development 环境验证首次上传、删除墓碑、离线队列和冲突合并。
- [ ] 用两台真机验证倒计时、秒表和番茄钟的暂停、恢复、延长、结束与重连。
- [ ] 验证两台在线设备各自提醒，晚到的过期同步不补发通知。
- [ ] 验证 Widget、锁屏 Live Activity、Dynamic Island 和结束二次确认。
- [ ] 上传 TestFlight，完成外部测试后再提交 App Store。
- [ ] 使用 Developer ID 签名、公证 Mac App，再更新 DMG 与 Homebrew cask。
