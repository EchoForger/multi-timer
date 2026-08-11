import Darwin
import Foundation
import MultiTimerCore

enum CLIError: Error, CustomStringConvertible {
    case usage(String)
    case unavailable
    case failed(String)

    var description: String {
        switch self {
        case .usage(let text), .failed(let text): return text
        case .unavailable: return "MultiTimer is not running. Open MultiTimer.app and try again."
        }
    }
}

func send(_ command: ControlCommand) throws -> ControlResponse {
    let descriptor = socket(AF_UNIX, SOCK_STREAM, 0)
    guard descriptor >= 0 else { throw CLIError.unavailable }
    defer { close(descriptor) }
    let path = MultiTimerPaths.socketURL.path
    var address = sockaddr_un()
    address.sun_family = sa_family_t(AF_UNIX)
    let pathCapacity = MemoryLayout.size(ofValue: address.sun_path)
    withUnsafeMutablePointer(to: &address.sun_path) { pointer in
        pointer.withMemoryRebound(to: CChar.self, capacity: pathCapacity) { destination in
            _ = path.withCString { source in
                strncpy(destination, source, pathCapacity - 1)
            }
        }
    }
    let length = socklen_t(MemoryLayout<sa_family_t>.size + path.utf8.count + 1)
    let result = withUnsafePointer(to: &address) {
        $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { connect(descriptor, $0, length) }
    }
    guard result == 0 else { throw CLIError.unavailable }
    let data = try ControlCodec.encode(command)
    data.withUnsafeBytes { raw in _ = write(descriptor, raw.baseAddress, raw.count) }
    var buffer = [UInt8](repeating: 0, count: 65_536)
    let count = read(descriptor, &buffer, buffer.count)
    guard count > 0 else { throw CLIError.unavailable }
    return try ControlCodec.decode(ControlResponse.self, from: Data(buffer.prefix(count)))
}

func parse(_ arguments: [String]) throws -> ControlCommand {
    guard let verb = arguments.first else {
        throw CLIError.usage("Usage: multitimer start [NAME] MINUTES | start --stopwatch [NAME] | list | pause ID_OR_NAME | cancel ID_OR_NAME | permissions | pomodoro start|pause|skip|stop|status")
    }
    let rest = Array(arguments.dropFirst())
    switch verb.lowercased() {
    case "start":
        if rest.first == "--stopwatch" {
            return ControlCommand(action: "stopwatch", name: rest.dropFirst().joined(separator: " "))
        }
        guard let duration = rest.last, let seconds = DurationParser.parse(duration) else {
            throw CLIError.usage("Usage: multitimer start [NAME] MINUTES")
        }
        let name = rest.dropLast().joined(separator: " ")
        return ControlCommand(action: "start", name: name.isEmpty ? "Timer" : name, seconds: seconds)
    case "list", "permissions": return ControlCommand(action: verb)
    case "pause", "cancel":
        guard !rest.isEmpty else { throw CLIError.usage("Usage: multitimer \(verb) ID_OR_NAME") }
        return ControlCommand(action: verb, arguments: [rest.joined(separator: " ")])
    case "pomodoro":
        return ControlCommand(action: "pomodoro", arguments: [rest.first ?? "status"])
    default: throw CLIError.usage("Unknown command: \(verb)")
    }
}

do {
    let command = try parse(Array(CommandLine.arguments.dropFirst()))
    var response: ControlResponse
    do {
        response = try send(command)
    } catch CLIError.unavailable {
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = ["-g", "-b", "io.github.echoforger.multitimer"]
        try? process.run()
        process.waitUntilExit()
        usleep(800_000)
        response = try send(command)
    }
    if !response.message.isEmpty { print(response.message) }
    response.lines.forEach { print($0) }
    if !response.ok { exit(1) }
} catch {
    fputs("multitimer: \(error)\n", stderr)
    exit(2)
}
