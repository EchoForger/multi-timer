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
final class AppDelegate: NSObject, NSApplicationDelegate, NSPopoverDelegate {
    static weak var shared: AppDelegate?

    private let model = AppModel.shared
    private let notifications = NotificationManager()
    private let updater = UpdateManager()
    private let cloudSync = CloudSyncService()
    private var statusItem: NSStatusItem?
    private let popover = NSPopover()
    private var auxiliaryWindows: [NSWindowController] = []
    private var controlServer: LocalControlServer?
    private var focusObservers: [NSObjectProtocol] = []
    private var localMouseMonitor: Any?

    func applicationDidFinishLaunching(_ notification: Notification) {
        Self.shared = self
        if let appearance = ProcessInfo.processInfo.environment["MULTITIMER_APPEARANCE"] {
            NSApp.appearance = NSAppearance(named: appearance == "dark" ? .darkAqua : .aqua)
        }
        NSApp.setActivationPolicy(.accessory)
        configureStatusItem()
        configureFocusDismissal()
        configureCallbacks()
        configureURLHandling()
        configureShortcut()
        configureControlServer()
        notifications.configure(model: model)
        cloudSync.configure(model: model)

        WindowRouter.shared.page = .timers
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.35) { [weak self] in
            self?.showPopover()
        }

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
            if model.presets.isEmpty {
                model.savePreset(TimerPreset(
                    name: "Tea",
                    durationSeconds: 300,
                    color: .teal,
                    favoriteRank: 0
                ))
                model.savePreset(TimerPreset(
                    name: "Deep Focus",
                    durationSeconds: 1_500,
                    color: .red,
                    sound: PresetSound(kind: .system, name: "Glass"),
                    earlyReminderMinutes: 5,
                    favoriteRank: 1
                ))
            }
            model.updateSettings { $0.showRemaining = true; $0.showCount = true }
            switch ProcessInfo.processInfo.environment["MULTITIMER_PREVIEW_PAGE"] {
            case "statistics":
                if model.pomodoro.phase == .idle { model.startPomodoro() }
                WindowRouter.shared.page = .statistics
            case "settings": WindowRouter.shared.page = .settings
            case "presets": WindowRouter.shared.page = .presets
            default: break
            }
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.8) { [weak self] in
                self?.showPopover()
                DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { self?.writePreviewSnapshotIfRequested() }
            }
        }
    }

    func applicationWillTerminate(_ notification: Notification) {
        controlServer?.stop()
        focusObservers.forEach(NotificationCenter.default.removeObserver)
        focusObservers.removeAll()
        if let localMouseMonitor {
            NSEvent.removeMonitor(localMouseMonitor)
            self.localMouseMonitor = nil
        }
    }

    func popoverWillClose(_ notification: Notification) {
        popover.contentViewController?.view.window?.makeFirstResponder(nil)
    }

    func popoverDidClose(_ notification: Notification) {
        WindowRouter.shared.page = .timers
    }

    private func configureStatusItem() {
        let root = PopoverView(model: model) { [weak self] height in
            self?.updatePopoverHeight(height)
        }
            .environmentObject(WindowRouter.shared)
            .preferredColorScheme(previewColorScheme)
        popover.behavior = .transient
        popover.animates = true
        popover.delegate = self
        popover.contentSize = NSSize(width: 360, height: 520)
        let hostingController = NSHostingController(rootView: root)
        hostingController.view.wantsLayer = true
        hostingController.view.layer?.backgroundColor = NSColor.clear.cgColor
        popover.contentViewController = hostingController

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

    private func configureFocusDismissal() {
        let center = NotificationCenter.default
        focusObservers.append(center.addObserver(
            forName: NSWindow.didResignKeyNotification,
            object: nil,
            queue: .main
        ) { [weak self] notification in
            Task { @MainActor in
                guard let self,
                      self.popover.isShown,
                      let popoverWindow = self.popover.contentViewController?.view.window,
                      notification.object as? NSWindow === popoverWindow else { return }
                DispatchQueue.main.async { [weak self, weak popoverWindow] in
                    guard let self,
                          popoverWindow?.isKeyWindow == false,
                          !self.hasActivePopoverDialog else { return }
                    self.closePopover()
                }
            }
        })

        focusObservers.append(center.addObserver(
            forName: NSApplication.didResignActiveNotification,
            object: NSApp,
            queue: .main
        ) { [weak self] _ in
            Task { @MainActor in self?.closePopover() }
        })

        localMouseMonitor = NSEvent.addLocalMonitorForEvents(
            matching: [.leftMouseDown, .rightMouseDown, .otherMouseDown]
        ) { [weak self] event in
            guard let self, self.popover.isShown else { return event }
            let statusWindow = self.statusItem?.button?.window
            if event.window !== statusWindow,
               !self.isPopoverInteractionWindow(event.window),
               !self.hasActivePopoverDialog {
                self.closePopover()
            }
            return event
        }
    }

    private var hasActivePopoverDialog: Bool {
        guard popover.isShown,
              let popoverWindow = popover.contentViewController?.view.window else { return false }
        if popoverWindow.attachedSheet != nil { return true }
        if isPopoverInteractionWindow(NSApp.keyWindow) { return true }
        if let modalWindow = NSApp.modalWindow,
           modalWindow !== popoverWindow {
            return true
        }
        return false
    }

    private func isPopoverInteractionWindow(_ window: NSWindow?) -> Bool {
        guard let window,
              let popoverWindow = popover.contentViewController?.view.window else { return false }
        if window === popoverWindow { return true }
        if window.sheetParent === popoverWindow || popoverWindow.attachedSheet === window { return true }
        if window.parent === popoverWindow { return true }
        return popoverWindow.childWindows?.contains(where: { $0 === window }) == true
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
        model.onTimerScheduled = { [weak self] timer in self?.notifications.scheduleEarlyReminder(for: timer) }
        model.onTimerRemoved = { [weak self] id in self?.notifications.removeScheduledReminders(for: id) }
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
        } else {
            WindowRouter.shared.page = .timers
            showPopover()
        }
    }

    func showPopover() {
        guard let button = statusItem?.button else { return }
        popover.show(relativeTo: button.bounds, of: button, preferredEdge: .minY)
        popover.contentViewController?.view.window?.makeKey()
    }

    private func closePopover() {
        guard popover.isShown else { return }
        popover.contentViewController?.view.window?.makeFirstResponder(nil)
        popover.performClose(nil)
    }

    private func updatePopoverHeight(_ height: CGFloat) {
        let size = NSSize(width: 360, height: height)
        guard popover.contentSize != size else { return }
        NSAnimationContext.runAnimationGroup { context in
            context.duration = 0.2
            popover.contentSize = size
        }
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

    @objc private func togglePomodoro() {
        if model.pomodoro.phase == .work || model.pomodoro.phase == .rest || model.pomodoro.phase == .longRest {
            model.togglePomodoroPause()
        }
        else { model.startPomodoro() }
    }
    @objc private func showStatisticsAction() { showStatistics() }
    @objc private func showSettingsAction() { showSettings() }
    @objc private func quitAction() { NSApp.terminate(nil) }

    func refreshStatusItem() {
        guard let button = statusItem?.button else { return }
        button.attributedTitle = NSAttributedString(string: "")
        let modules = statusModules()
        if modules.isEmpty {
            let symbol = model.timers.contains(where: { $0.finished }) ? "timer.circle.fill" : "timer"
            let image = NSImage(systemSymbolName: symbol, accessibilityDescription: "MultiTimer")
            image?.isTemplate = true
            button.image = image
        } else {
            button.image = composeStatusImage(modules: modules)
        }
        button.toolTip = "MultiTimer"
    }

    private struct StatusModule {
        let symbol: String
        let text: String
        /// Capsule fill color, or `nil` for a transparent module.
        let fill: NSColor?
    }

    private func statusModules() -> [StatusModule] {
        var modules: [StatusModule] = []
        switch model.pomodoro.phase {
        case .work:
            modules.append(StatusModule(
                symbol: "flame.fill",
                text: TimeFormat.menuBar(model.pomodoroRemaining),
                fill: .systemRed
            ))
        case .rest:
            modules.append(StatusModule(
                symbol: "cup.and.saucer.fill",
                text: TimeFormat.menuBar(model.pomodoroRemaining),
                fill: .systemGreen
            ))
        case .longRest:
            modules.append(StatusModule(
                symbol: "bed.double.fill",
                text: TimeFormat.menuBar(model.pomodoroRemaining),
                fill: .systemGreen
            ))
        default:
            break
        }
        if model.settings.showRemaining, let remaining = model.nearestRemaining {
            modules.append(StatusModule(symbol: "timer", text: TimeFormat.menuBar(remaining), fill: nil))
        }
        if model.settings.showCount, let elapsed = model.nearestStopwatchElapsed {
            modules.append(StatusModule(symbol: "stopwatch.fill", text: TimeFormat.menuBar(elapsed), fill: nil))
        }
        return modules
    }

    private func composeStatusImage(modules: [StatusModule]) -> NSImage? {
        let height: CGFloat = 18
        let horizontalPadding: CGFloat = 6
        let iconTextSpacing: CGFloat = 4
        let moduleGap: CGFloat = 4
        let cornerRadius: CGFloat = 5
        let font = NSFont.monospacedDigitSystemFont(ofSize: NSFont.systemFontSize, weight: .medium)
        let symbolConfiguration = NSImage.SymbolConfiguration(pointSize: 11, weight: .semibold)

        struct ModuleLayout {
            let module: StatusModule
            let baseSymbol: NSImage
            let symbolSize: NSSize
            let textWidth: CGFloat
            let width: CGFloat
            let originX: CGFloat
        }

        var layouts: [ModuleLayout] = []
        var cursor: CGFloat = 0
        for module in modules {
            guard let baseSymbol = NSImage(systemSymbolName: module.symbol, accessibilityDescription: nil)?
                .withSymbolConfiguration(symbolConfiguration) else { continue }
            let textWidth = ceil((module.text as NSString).size(withAttributes: [.font: font]).width)
            let width = horizontalPadding * 2 + baseSymbol.size.width + iconTextSpacing + textWidth
            layouts.append(ModuleLayout(
                module: module,
                baseSymbol: baseSymbol,
                symbolSize: baseSymbol.size,
                textWidth: textWidth,
                width: width,
                originX: cursor
            ))
            cursor += width + moduleGap
        }
        guard !layouts.isEmpty else { return nil }
        let totalWidth = cursor - moduleGap

        let image = NSImage(size: NSSize(width: totalWidth, height: height), flipped: false) { _ in
            for layout in layouts {
                let rect = NSRect(x: layout.originX, y: 0, width: layout.width, height: height)
                let symbolForeground: NSColor = layout.module.fill == nil ? .labelColor : .white
                let textForeground: NSColor = .white

                if let fill = layout.module.fill {
                    fill.setFill()
                    NSBezierPath(
                        roundedRect: rect.insetBy(dx: 1, dy: 1),
                        xRadius: cornerRadius,
                        yRadius: cornerRadius
                    ).fill()
                }

                let symbol = layout.baseSymbol.withSymbolConfiguration(
                    symbolConfiguration.applying(NSImage.SymbolConfiguration(paletteColors: [symbolForeground]))
                ) ?? layout.baseSymbol
                let symbolOrigin = NSPoint(
                    x: rect.minX + horizontalPadding,
                    y: rect.midY - layout.symbolSize.height / 2
                )
                symbol.draw(at: symbolOrigin, from: .zero, operation: .sourceOver, fraction: 1)

                let textAttributes: [NSAttributedString.Key: Any] = [.font: font, .foregroundColor: textForeground]
                let textSize = (layout.module.text as NSString).size(withAttributes: textAttributes)
                let textOrigin = NSPoint(
                    x: symbolOrigin.x + layout.symbolSize.width + iconTextSpacing,
                    y: rect.midY - textSize.height / 2
                )
                (layout.module.text as NSString).draw(at: textOrigin, withAttributes: textAttributes)
            }
            return true
        }
        image.isTemplate = false
        image.accessibilityDescription = "MultiTimer"
        return image
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
        let name = query.first(where: { $0.name == "name" })?.value ?? ""
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
            model.startCountdown(label: command.name ?? "", seconds: command.seconds ?? 60)
            return ControlResponse(ok: true, message: "Timer started")
        case "stopwatch":
            model.startStopwatch(label: command.name ?? "")
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
        WindowRouter.shared.page = .statistics
        if !popover.isShown { DispatchQueue.main.async { [weak self] in self?.showPopover() } }
    }

    func showSettings() {
        WindowRouter.shared.page = .settings
        if !popover.isShown { DispatchQueue.main.async { [weak self] in self?.showPopover() } }
    }

    func showPermissions() {
        showWindow(title: NSLocalizedString("MultiTimer Permissions", comment: "Window title"), size: NSSize(width: 610, height: 490)) {
            PermissionsView(notificationManager: notifications)
        }
    }

    func showAbout() {
        showWindow(
            title: NSLocalizedString("About MultiTimer", comment: "Window title"),
            size: NSSize(width: 420, height: 384),
            resizable: false
        ) {
            AboutView(
                version: appVersion,
                build: appBuild,
                onWebsite: { NSWorkspace.shared.open(URL(string: "https://echoforger.github.io/multi-timer/")!) },
                onCheckUpdates: { [weak self] in self?.checkForUpdates() }
            )
            .preferredColorScheme(previewColorScheme)
        }
    }

    func checkForUpdates(interactive: Bool = true) {
        updater.check(currentVersion: appVersion, skippedVersion: model.skippedUpdate) { [weak self] result in
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

    private var appVersion: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "0.9.0"
    }

    private var appBuild: String {
        Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "0"
    }

    private func showWindow<Content: View>(
        title: String,
        size: NSSize,
        resizable: Bool = true,
        @ViewBuilder content: () -> Content
    ) {
        popover.performClose(nil)
        NSApp.setActivationPolicy(.regular)
        NSApp.activate(ignoringOtherApps: true)
        var style: NSWindow.StyleMask = [.titled, .closable, .miniaturizable, .fullSizeContentView]
        if resizable { style.insert(.resizable) }
        let window = NSWindow(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: style,
            backing: .buffered,
            defer: false
        )
        window.title = title
        window.titleVisibility = .hidden
        window.titlebarAppearsTransparent = true
        window.isMovableByWindowBackground = true
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
    @Published var page: PopoverPage = .timers

    func main() { page = .timers }
    func presets() { page = .presets }
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
