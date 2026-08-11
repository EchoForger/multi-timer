import AppKit
import Foundation
import MultiTimerCore

struct ReleaseInfo {
    let version: String
    let title: String
    let notes: String
    let pageURL: URL
    let dmgURL: URL
    let checksumURL: URL
}

enum UpdateError: LocalizedError {
    case invalidResponse
    case installFailed(String)

    var errorDescription: String? {
        switch self {
        case .invalidResponse: return "GitHub did not return a valid release. Please try again later."
        case .installFailed(let message): return message
        }
    }
}

final class UpdateManager: @unchecked Sendable {
    private let session: URLSession

    init(session: URLSession = .shared) { self.session = session }

    func check(
        currentVersion: String,
        skippedVersion: String?,
        completion: @escaping (Result<ReleaseInfo?, Error>) -> Void
    ) {
        guard let url = URL(string: "https://github.com/EchoForger/multi-timer/releases/latest") else {
            completion(.failure(UpdateError.invalidResponse)); return
        }
        session.dataTask(with: url) { [weak self] _, response, error in
            if let error { completion(.failure(error)); return }
            guard let finalURL = response?.url,
                  let tag = finalURL.pathComponents.last,
                  tag.lowercased().hasPrefix("v") else {
                completion(.failure(UpdateError.invalidResponse)); return
            }
            let version = String(tag.dropFirst())
            guard VersionNumber.compare(currentVersion, version) == .orderedAscending,
                  skippedVersion != version else { completion(.success(nil)); return }
            self?.fetchNotes(version: version, pageURL: finalURL, completion: completion)
        }.resume()
    }

    private func fetchNotes(
        version: String,
        pageURL: URL,
        completion: @escaping (Result<ReleaseInfo?, Error>) -> Void
    ) {
        let assetRoot = "https://github.com/EchoForger/multi-timer/releases/download/v\(version)"
        let fallback = ReleaseInfo(
            version: version,
            title: "MultiTimer \(version)",
            notes: "Open the release page to see everything included in this update.",
            pageURL: pageURL,
            dmgURL: URL(string: "\(assetRoot)/MultiTimer-\(version).dmg")!,
            checksumURL: URL(string: "\(assetRoot)/MultiTimer-\(version).dmg.sha256")!
        )
        guard let feedURL = URL(string: "https://github.com/EchoForger/multi-timer/releases.atom") else {
            completion(.success(fallback)); return
        }
        session.dataTask(with: feedURL) { data, _, _ in
            guard let data, let xml = String(data: data, encoding: .utf8) else {
                completion(.success(fallback)); return
            }
            let escapedVersion = NSRegularExpression.escapedPattern(for: version)
            let entryPattern = "(?s)<entry>.*?<id>[^<]*/tag/v\(escapedVersion)</id>.*?</entry>"
            let entry = xml.firstMatch(entryPattern) ?? ""
            let title = entry.firstMatch(#"(?s)<title[^>]*>(.*?)</title>"#, group: 1)
                .map(Self.decodeHTML) ?? fallback.title
            let rawNotes = entry.firstMatch(#"(?s)<content[^>]*>(.*?)</content>"#, group: 1)
                .map(Self.decodeHTML) ?? fallback.notes
            let notes = Self.plainText(fromHTML: rawNotes)
            completion(.success(ReleaseInfo(
                version: version,
                title: title,
                notes: notes.isEmpty ? fallback.notes : notes,
                pageURL: pageURL,
                dmgURL: fallback.dmgURL,
                checksumURL: fallback.checksumURL
            )))
        }.resume()
    }

    @MainActor
    func present(release: ReleaseInfo, model: AppModel) {
        let alert = NSAlert()
        alert.alertStyle = .informational
        alert.messageText = String(format: NSLocalizedString("MultiTimer %@ is available", comment: "Update"), release.version)
        alert.informativeText = NSLocalizedString("Review what’s new, then choose when to update.", comment: "Update")
        alert.addButton(withTitle: NSLocalizedString("Update Now", comment: "Update"))
        alert.addButton(withTitle: NSLocalizedString("Remind Me Later", comment: "Update"))
        alert.addButton(withTitle: NSLocalizedString("Skip This Version", comment: "Update"))
        let scroll = NSScrollView(frame: NSRect(x: 0, y: 0, width: 450, height: 190))
        scroll.hasVerticalScroller = true
        scroll.borderType = .bezelBorder
        let text = NSTextView(frame: scroll.bounds)
        text.isEditable = false
        text.drawsBackground = false
        text.textContainerInset = NSSize(width: 8, height: 8)
        text.string = release.notes
        scroll.documentView = text
        alert.accessoryView = scroll
        NSApp.activate(ignoringOtherApps: true)
        switch alert.runModal() {
        case .alertFirstButtonReturn: install(release: release)
        case .alertThirdButtonReturn: model.skip(version: release.version)
        default: break
        }
    }

    @MainActor
    private func install(release: ReleaseInfo) {
        let source = InstallationSource.detect()
        let confirmation = NSAlert()
        confirmation.messageText = NSLocalizedString("Install this update now?", comment: "Update")
        confirmation.informativeText = source == .homebrew
            ? "MultiTimer will run `brew upgrade --cask echoforger/tap/multi-timer` in the background."
            : "MultiTimer will download the verified DMG from GitHub Releases, replace the current app, and reopen it."
        confirmation.addButton(withTitle: NSLocalizedString("Install", comment: "Update"))
        confirmation.addButton(withTitle: NSLocalizedString("Cancel", comment: "Update"))
        guard confirmation.runModal() == .alertFirstButtonReturn else { return }

        DispatchQueue.global(qos: .userInitiated).async { [weak self] in
            do {
                if source == .homebrew { try self?.installWithHomebrew() }
                else { try self?.installDMG(release) }
            } catch {
                DispatchQueue.main.async {
                    let alert = NSAlert(error: error)
                    alert.messageText = NSLocalizedString("Update Failed", comment: "Update")
                    alert.runModal()
                }
            }
        }
    }

    private func installWithHomebrew() throws {
        let candidates = ["/opt/homebrew/bin/brew", "/usr/local/bin/brew"]
        guard let brew = candidates.first(where: { FileManager.default.isExecutableFile(atPath: $0) }) else {
            throw UpdateError.installFailed("Homebrew could not be found.")
        }
        let output = try run(brew, ["upgrade", "--cask", "echoforger/tap/multi-timer"])
        guard output.status == 0 else { throw UpdateError.installFailed(output.text) }
        DispatchQueue.main.async { NSApp.terminate(nil) }
    }

    private func installDMG(_ release: ReleaseInfo) throws {
        let manager = FileManager.default
        let directory = manager.temporaryDirectory.appendingPathComponent("MultiTimer-update-\(UUID().uuidString)")
        try manager.createDirectory(at: directory, withIntermediateDirectories: true)
        defer { try? manager.removeItem(at: directory) }
        let dmg = directory.appendingPathComponent("MultiTimer.dmg")
        let checksum = directory.appendingPathComponent("MultiTimer.dmg.sha256")
        try Data(contentsOf: release.dmgURL).write(to: dmg)
        try Data(contentsOf: release.checksumURL).write(to: checksum)
        let expected = try String(contentsOf: checksum).split(whereSeparator: \.isWhitespace).first.map(String.init) ?? ""
        let actual = try run("/usr/bin/shasum", ["-a", "256", dmg.path]).text.split(whereSeparator: \.isWhitespace).first.map(String.init) ?? ""
        guard !expected.isEmpty, expected.lowercased() == actual.lowercased() else {
            throw UpdateError.installFailed("The downloaded update failed SHA-256 verification.")
        }
        let mount = directory.appendingPathComponent("mount")
        try manager.createDirectory(at: mount, withIntermediateDirectories: true)
        let mounted = try run("/usr/bin/hdiutil", ["attach", dmg.path, "-nobrowse", "-readonly", "-mountpoint", mount.path])
        guard mounted.status == 0 else { throw UpdateError.installFailed(mounted.text) }
        defer { _ = try? run("/usr/bin/hdiutil", ["detach", mount.path, "-force"]) }
        let candidate = mount.appendingPathComponent("MultiTimer.app")
        let plist = candidate.appendingPathComponent("Contents/Info.plist").path
        let identifier = try run("/usr/libexec/PlistBuddy", ["-c", "Print :CFBundleIdentifier", plist])
        guard identifier.text.trimmingCharacters(in: .whitespacesAndNewlines) == "io.github.echoforger.multitimer" else {
            throw UpdateError.installFailed("The downloaded app has an unexpected bundle identifier.")
        }
        let destination = Bundle.main.bundleURL
        let backup = destination.deletingLastPathComponent().appendingPathComponent(".MultiTimer.backup.app")
        try? manager.removeItem(at: backup)
        try manager.moveItem(at: destination, to: backup)
        do { try manager.copyItem(at: candidate, to: destination) }
        catch {
            try? manager.moveItem(at: backup, to: destination)
            throw error
        }
        try? manager.removeItem(at: backup)
        DispatchQueue.main.async {
            NSWorkspace.shared.openApplication(at: destination, configuration: NSWorkspace.OpenConfiguration())
            NSApp.terminate(nil)
        }
    }

    private func run(_ executable: String, _ arguments: [String]) throws -> (status: Int32, text: String) {
        let process = Process()
        let pipe = Pipe()
        process.executableURL = URL(fileURLWithPath: executable)
        process.arguments = arguments
        process.standardOutput = pipe
        process.standardError = pipe
        try process.run()
        process.waitUntilExit()
        let text = String(data: pipe.fileHandleForReading.readDataToEndOfFile(), encoding: .utf8) ?? ""
        return (process.terminationStatus, text)
    }

    private static func decodeHTML(_ value: String) -> String {
        value.replacingOccurrences(of: "&lt;", with: "<")
            .replacingOccurrences(of: "&gt;", with: ">")
            .replacingOccurrences(of: "&amp;", with: "&")
            .replacingOccurrences(of: "&quot;", with: "\"")
            .replacingOccurrences(of: "&#39;", with: "'")
    }

    private static func plainText(fromHTML html: String) -> String {
        let lines = html.replacingOccurrences(of: #"(?i)</?(p|div|li|h[1-6]|br)[^>]*>"#, with: "\n", options: .regularExpression)
        return lines.replacingOccurrences(of: #"<[^>]+>"#, with: "", options: .regularExpression)
            .replacingOccurrences(of: #"\n{3,}"#, with: "\n\n", options: .regularExpression)
            .trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

private enum InstallationSource: Equatable {
    case homebrew, dmg

    static func detect() -> Self {
        let path = Bundle.main.bundleURL.resolvingSymlinksInPath().path.lowercased()
        if path.contains("/caskroom/multi-timer/") {
            return .homebrew
        }
        return .dmg
    }
}

private extension String {
    func firstMatch(_ pattern: String, group: Int = 0) -> String? {
        guard let regex = try? NSRegularExpression(pattern: pattern),
              let match = regex.firstMatch(in: self, range: NSRange(startIndex..., in: self)),
              let range = Range(match.range(at: group), in: self) else { return nil }
        return String(self[range])
    }
}
