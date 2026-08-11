import Darwin
import Foundation
import MultiTimerCore

@MainActor
final class LocalControlServer {
    private let handler: (ControlCommand) -> ControlResponse
    private var socketDescriptor: Int32 = -1
    private var source: DispatchSourceRead?
    private let socketPath = MultiTimerPaths.socketURL.path

    init(handler: @escaping (ControlCommand) -> ControlResponse) {
        self.handler = handler
    }

    func start() throws {
        try FileManager.default.createDirectory(
            at: MultiTimerPaths.socketURL.deletingLastPathComponent(),
            withIntermediateDirectories: true
        )
        unlink(socketPath)
        socketDescriptor = socket(AF_UNIX, SOCK_STREAM, 0)
        guard socketDescriptor >= 0 else { throw POSIXError(.ENOTSOCK) }

        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let pathCapacity = MemoryLayout.size(ofValue: address.sun_path)
        guard socketPath.utf8.count < pathCapacity else {
            throw POSIXError(.ENAMETOOLONG)
        }
        withUnsafeMutablePointer(to: &address.sun_path) { pointer in
            pointer.withMemoryRebound(to: CChar.self, capacity: pathCapacity) { destination in
                _ = socketPath.withCString { source in
                    strncpy(destination, source, pathCapacity - 1)
                }
            }
        }
        let length = socklen_t(MemoryLayout<sa_family_t>.size + socketPath.utf8.count + 1)
        let bindResult = withUnsafePointer(to: &address) {
            $0.withMemoryRebound(to: sockaddr.self, capacity: 1) { Darwin.bind(socketDescriptor, $0, length) }
        }
        guard bindResult == 0, listen(socketDescriptor, 8) == 0 else {
            let error = errno
            close(socketDescriptor)
            socketDescriptor = -1
            throw POSIXError(POSIXErrorCode(rawValue: error) ?? .EIO)
        }
        chmod(socketPath, S_IRUSR | S_IWUSR)
        let readSource = DispatchSource.makeReadSource(fileDescriptor: socketDescriptor, queue: .main)
        readSource.setEventHandler { [weak self] in self?.acceptConnections() }
        readSource.setCancelHandler { [socketDescriptor] in if socketDescriptor >= 0 { close(socketDescriptor) } }
        source = readSource
        readSource.resume()
    }

    func stop() {
        source?.cancel()
        source = nil
        socketDescriptor = -1
        unlink(socketPath)
    }

    private func acceptConnections() {
        while true {
            let client = accept(socketDescriptor, nil, nil)
            if client < 0 { break }
            var buffer = [UInt8](repeating: 0, count: 65_536)
            let count = read(client, &buffer, buffer.count)
            let response: ControlResponse
            if count > 0, let command = try? ControlCodec.decode(ControlCommand.self, from: Data(buffer.prefix(count))) {
                response = handler(command)
            } else {
                response = ControlResponse(ok: false, message: "Invalid command")
            }
            if let data = try? ControlCodec.encode(response) {
                data.withUnsafeBytes { raw in _ = write(client, raw.baseAddress, raw.count) }
            }
            close(client)
        }
    }
}
