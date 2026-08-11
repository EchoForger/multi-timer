import AppKit
import KeyboardShortcuts
import LaunchAtLogin
import MultiTimerCore
import SwiftUI

extension KeyboardShortcuts.Name {
    static let openPermissions = Self(
        "openPermissions",
        default: .init(.m, modifiers: [.command, .shift, .option])
    )
}

@main
struct MultiTimerApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate

    init() {
        LaunchAtLogin.migrateIfNeeded()
    }

    var body: some Scene {
        Settings { EmptyView() }
    }
}

@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    static weak var shared: AppDelegate?

    private let model = AppModel.shared
    private let notifications = NotificationManager()
    private let updater = UpdateManager()
    private let cloudSync = CloudSyncService()
    private var statusItem: NSStatusItem?
    private let popover = NSPopover()
    private var auxiliaryWindows: [NSWindowController] = []
    private var controlServer: LocalControlServer?

    func applicationDidFinishLaunching(_ notification: Notification) {
        Self.shared = self
        if let appearance = ProcessInfo.processInfo.environment["MULTITIMER_APPEARANCE"] {
            NSApp.appearance = NSAppearance(named: appearance == "dark" ? .darkAqua : .aqua)
        }
        NSApp.setActivationPolicy(.accessory)
        configureStatusItem()
        configureCallbacks()
        configureURLHandling()
        configureShortcut()
        configureControlServer()
        notifications.configure(model: model)
        cloudSync.configure(model: model)

        DispatchQueue.main.asyncAfter(deadline: .now() + 1) { [weak self] in
            self?.refreshStatusItem()
            self?.checkStartupPermissions()
        }
        if model.settings.updateAutomatically {
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.5) { [weak self] in
                self?.checkForUpdates(interactive: false)
            }
        }
        if ProcessInfo.processInfo.environment["MULTITIMER_PREVIEW"] == "1" {
            if model.timers.isEmpty {
                model.startCountdown(label: "Design review", seconds: 12 * 60)
                model.startCountdown(label: "Tea", seconds: 5 * 60)
                model.startStopwatch(label: "Deep work")
            }
            model.updateSettings { $0.showRemaining = true; $0.showCount = true }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak self] in
                self?.showPopover()
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self?.writePreviewSnapshotIfRequested() }
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        controlServer?.stop()
    }

    private func configureStatusItem() {
        let root = PopoverView(model: model)
            .environmentObject(WindowRouter.shared)
            .preferredColorScheme(previewColorScheme)
        popover.behavior = .transient
        popover.animates = true
        popover.contentSize = NSSize(width: 360, height: 640)
        popover.contentViewController = NSHostingController(rootView: root)

        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        guard let button = statusItem?.button else { return }
        let image = NSImage(systemSymbolName: "timer", accessibilityDescription: "MultiTimer")
        image?.isTemplate = true
        button.image = image
        button.imagePosition = .imageLeft
        button.target = self
        button.action = #selector(togglePopover(_:))
        button.sendAction(on: [.leftMouseUp, .rightMouseUp])
        refreshStatusItem()
    }

    private var previewColorScheme: ColorScheme? {
        switch ProcessInfo.processInfo.environment["MULTITIMER_APPEARANCE"] {
        case "light": return .light
        case "dark": return .dark
        default: return nil
        }
    }

    private func configureCallbacks() {
        model.onStatusChanged = { [weak self] in self?.refreshStatusItem() }
        model.onPersistenceChanged = { [weak self] in self?.cloudSync.push() }
        model.onTimerFinished = { [weak self] timer in self?.notifications.timerFinished(timer) }
        model.onPomodoroFinished = { [weak self] phase in self?.notifications.pomodoroFinished(phase) }
        WindowRouter.shared.delegate = self
    }

    private func configureURLHandling() {
        NSAppleEventManager.shared().setEventHandler(
            self,
            andSelector: #selector(handleGetURL(_:reply:)),
            forEventClass: AEEventClass(kInternetEventClass),
            andEventID: AEEventID(kAEGetURL)
        )
    }

    private func configureShortcut() {
        KeyboardShortcuts.onKeyUp(for: .openPermissions) { [weak self] in
            Task { @MainActor in self?.showPermissions() }
        }
    }

    private func configureControlServer() {
        controlServer = LocalControlServer { [weak self] command in
            guard let self else { return ControlResponse(ok: false, message: "MultiTimer is unavailable") }
            return self.handle(command)
        }
        try? controlServer?.start()
    }

    @objc private func togglePopover(_ sender: Any?) {
        guard let event = NSApp.currentEvent else { return }
        if event.type == .rightMouseUp {
            showContextMenu()
            return
        }
        if popover.isShown {
            popover.performClose(sender)
        } else { showPopover() }
    }

    private func showPopover() {
        guard let button = statusItem?.button else { return }
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover.contentViewController?.view.window?.makeKey()
    }

    private func writePreviewSnapshotIfRequested() {
        guard let path = ProcessInfo.processInfo.environment["MULTITIMER_SNAPSHOT_PATH"],
              let view = popover.contentViewController?.view else { return }
        let bounds = view.bounds
        guard let bitmap = view.bitmapImageRepForCachingDisplay(in: bounds) else { return }
        view.cacheDisplay(in: bounds, to: bitmap)
        guard let data = bitmap.representation(using: .png, properties: [:]) else { return }
        try? data.write(to: URL(fileURLWithPath: path), options: .atomic)
    }

    private func showContextMenu() {
        let menu = NSMenu()
        menu.addItem(withTitle: NSLocalizedString("New 5 Minute Timer", comment: "Status menu"), action: #selector(startQuickTimer), keyEquivalent: "")
        menu.addItem(withTitle: NSLocalizedString("Start / Pause Pomodoro", comment: "Status menu"), action: #selector(togglePomodoro), keyEquivalent: "")
        menu.addItem(.separator())
        menu.addItem(withTitle: NSLocalizedString("Statistics", comment: "Status menu"), action: #selector(showStatisticsAction), keyEquivalent: "")
        menu.addItem(withTitle: NSLocalizedString("Settings", comment: "Status menu"), action: #selector(showSettingsAction), keyEquivalent: ",")
        menu.addItem(.separator())
        menu.addItem(withTitle: NSLocalizedString("Quit MultiTimer", comment: "Status menu"), action: #selector(quitAction), keyEquivalent: "q")
        menu.items.forEach { $0.target = self }
        statusItem?.menu = menu
        statusItem?.button?.performClick(nil)
        statusItem?.menu = nil
    }

    @objc private func startQuickTimer() { model.startCountdown(label: "Timer", seconds: 300) }
    @objc private func togglePomodoro() {
        if model.pomodoro.phase == .work || model.pomodoro.phase == .rest { model.togglePomodoroPause() }
        else { model.startPomodoro() }
    }
    @objc private func showStatisticsAction() { showStatistics() }
    @objc private func showSettingsAction() { showSettings() }
    @objc private func quitAction() { NSApp.terminate(nil) }

    func refreshStatusItem() {
        guard let button = statusItem?.button else { return }
        let symbol: String
        switch model.pomodoro.phase {
        case .work: symbol = "flame.fill"
        case .rest: symbol = "cup.and.saucer.fill"
        default: symbol = model.timers.contains(where: { $0.finished }) ? "timer.circle.fill" : "timer"
        }
        let image = NSImage(systemSymbolName: symbol, accessibilityDescription: "MultiTimer")
        image?.isTemplate = true
        button.image = image
        var parts: [String] = []
        if model.pomodoro.phase == .work || model.pomodoro.phase == .rest {
            parts.append(TimeFormat.menuBar(model.pomodoroRemaining))
        } else if model.settings.showRemaining, let remaining = model.nearestRemaining {
            parts.append(TimeFormat.menuBar(remaining))
        }
        if model.settings.showCount, model.activeCount > 0 { parts.append("\(model.activeCount)") }
        let title = parts.isEmpty ? "" : " " + parts.joined(separator: " · ")
        button.attributedTitle = NSAttributedString(
            string: title,
            attributes: [.font: NSFont.monospacedDigitSystemFont(ofSize: NSFont.systemFontSize, weight: .regular)]
        )
        button.toolTip = "MultiTimer"
    }

    @objc private func handleGetURL(_ event: NSAppleEventDescriptor, reply: NSAppleEventDescriptor) {
        guard let value = event.paramDescriptor(forKeyword: keyDirectObject)?.stringValue,
              let url = URL(string: value) else { return }
        handle(url: url)
    }

    private func handle(url: URL) {
        guard url.scheme?.lowercased() == "multitimer" else { return }
        let host = url.host?.lowercased() ?? ""
        let path = url.path.trimmingCharacters(in: CharacterSet(charactersIn: "/")).lowercased()
        let query = URLComponents(url: url, resolvingAgainstBaseURL: false)?.queryItems ?? []
        let name = query.first(where: { $0.name == "name" })?.value ?? "Timer"
        if host == "start" {
            if query.first(where: { $0.name == "stopwatch" })?.value == "1" {
                model.startStopwatch(label: name)
            } else if let seconds = query.first(where: { $0.name == "seconds" })?.value.flatMap(Int.init) {
                model.startCountdown(label: name, seconds: seconds)
            } else if let minutes = query.first(where: { $0.name == "minutes" })?.value.flatMap(Double.init) {
                model.startCountdown(label: name, seconds: Int(minutes * 60))
            }
        } else if host == "pomodoro" {
            switch path {
            case "start": model.startPomodoro()
            case "pause": model.togglePomodoroPause()
            case "skip": model.skipPomodoro()
            case "stop": model.stopPomodoro()
            default: break
            }
        } else if host == "permissions" {
            showPermissions()
        }
    }

    private func handle(_ command: ControlCommand) -> ControlResponse {
        switch command.action {
        case "start":
            model.startCountdown(label: command.name ?? "Timer", seconds: command.seconds ?? 60)
            return ControlResponse(ok: true, message: "Timer started")
        case "stopwatch":
            model.startStopwatch(label: command.name ?? "Stopwatch")
            return ControlResponse(ok: true, message: "Stopwatch started")
        case "list":
            let lines = model.sortedTimers.map { timer in
                let value = timer.kind == .countdown ? TimeFormat.clock(timer.remaining(at: model.now)) : TimeFormat.clock(timer.elapsed(at: model.now))
                return "\(timer.id.prefix(8))\t\(value)\t\(timer.label)"
            }
            return ControlResponse(ok: true, lines: lines)
        case "pause":
            guard let value = command.arguments.first, let timer = model.timer(matching: value) else {
                return ControlResponse(ok: false, message: "Timer not found")
            }
            model.togglePause(timer.id)
            return ControlResponse(ok: true, message: timer.isPaused ? "Timer resumed" : "Timer paused")
        case "cancel":
            guard let value = command.arguments.first, let timer = model.timer(matching: value) else {
                return ControlResponse(ok: false, message: "Timer not found")
            }
            model.cancel(timer.id)
            return ControlResponse(ok: true, message: "Timer cancelled")
        case "permissions":
            showPermissions()
            return ControlResponse(ok: true, message: "Permissions opened")
        case "pomodoro":
            switch command.arguments.first ?? "status" {
            case "start": model.startPomodoro()
            case "pause": model.togglePomodoroPause()
            case "skip": model.skipPomodoro()
            case "stop": model.stopPomodoro()
            default:
                return ControlResponse(ok: true, message: "\(model.pomodoro.phase.rawValue) \(TimeFormat.clock(model.pomodoroRemaining))")
            }
            return ControlResponse(ok: true, message: "Pomodoro \(model.pomodoro.phase.rawValue)")
        default:
            return ControlResponse(ok: false, message: "Unknown command")
        }
    }

    private func checkStartupPermissions() {
        notifications.authorizationStatus { status in
            guard status == .denied else { return }
            DispatchQueue.main.async { [weak self] in self?.showPermissions() }
        }
    }

    func showStatistics() {
        showWindow(title: NSLocalizedString("MultiTimer Statistics", comment: "Window title"), size: NSSize(width: 680, height: 520)) {
            StatisticsView(model: model)
        }
    }

    func showSettings() {
        showWindow(title: NSLocalizedString("MultiTimer Settings", comment: "Window title"), size: NSSize(width: 520, height: 470)) {
            SettingsView(model: model)
        }
    }

    func showPermissions() {
        showWindow(title: NSLocalizedString("MultiTimer Permissions", comment: "Window title"), size: NSSize(width: 610, height: 490)) {
            PermissionsView(notificationManager: notifications)
        }
    }

    func showAbout() {
        let credits = NSAttributedString(string: "MultiTimer 0.7.0\n© 2026 EchoForger\nOpen source under the MIT License.")
        NSApp.activate(ignoringOtherApps: true)
        NSApp.orderFrontStandardAboutPanel(options: [
            .applicationName: "MultiTimer",
            .applicationVersion: "0.7.0",
            .version: "0.7.0",
            .credits: credits,
        ])
    }

    func checkForUpdates(interactive: Bool = true) {
        updater.check(currentVersion: "0.7.0", skippedVersion: model.skippedUpdate) { [weak self] result in
            Task { @MainActor in
                guard let self else { return }
                switch result {
                case .success(let release?): self.updater.present(release: release, model: self.model)
                case .success(nil) where interactive:
                    let alert = NSAlert()
                    alert.messageText = NSLocalizedString("MultiTimer is up to date", comment: "Update")
                    alert.informativeText = NSLocalizedString("You already have the latest version.", comment: "Update")
                    alert.runModal()
                case .failure(let error) where interactive:
                    let alert = NSAlert(error: error)
                    alert.messageText = NSLocalizedString("Unable to Check for Updates", comment: "Update error")
                    alert.runModal()
                default: break
                }
            }
        }
    }

    private func showWindow<Content: View>(title: String, size: NSSize, @ViewBuilder content: () -> Content) {
        popover.performClose(nil)
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: [.titled, .closable, .miniaturizable, .resizable],
            backing: .buffered,
            defer: false
        )
        window.title = title
        window.center()
        window.isReleasedWhenClosed = false
        window.contentViewController = NSHostingController(rootView: content())
        let controller = ClosingWindowController(window: window) { [weak self] controller in
            self?.auxiliaryWindows.removeAll { $0 === controller }
            if self?.auxiliaryWindows.isEmpty == true { NSApp.setActivationPolicy(.accessory) }
        }
        auxiliaryWindows.append(controller)
        controller.showWindow(nil)
    }
}

@MainActor
final class WindowRouter: ObservableObject {
    static let shared = WindowRouter()
    weak var delegate: AppDelegate?

    func statistics() { delegate?.showStatistics() }
    func settings() { delegate?.showSettings() }
    func permissions() { delegate?.showPermissions() }
    func about() { delegate?.showAbout() }
    func updates() { delegate?.checkForUpdates() }
}

private final class ClosingWindowController: NSWindowController, NSWindowDelegate {
    private let onClose: (NSWindowController) -> Void

    init(window: NSWindow, onClose: @escaping (NSWindowController) -> Void) {
        self.onClose = onClose
        super.init(window: window)
        window.delegate = self
    }

    required init?(coder: NSCoder) { nil }

    func windowWillClose(_ notification: Notification) { onClose(self) }
}
