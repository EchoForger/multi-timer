import Foundation

public struct ControlCommand: Codable, Sendable {
    public var action: String
    public var arguments: [String]
    public var name: String?
    public var seconds: Int?

    public init(action: String, arguments: [String] = [], name: String? = nil, seconds: Int? = nil) {
        self.action = action
        self.arguments = arguments
        self.name = name
        self.seconds = seconds
    }
}

public struct ControlResponse: Codable, Sendable {
    public var ok: Bool
    public var message: String
    public var lines: [String]

    public init(ok: Bool, message: String = "", lines: [String] = []) {
        self.ok = ok
        self.message = message
        self.lines = lines
    }
}

public enum ControlCodec {
    public static func encode<T: Encodable>(_ value: T) throws -> Data {
        var data = try JSONEncoder().encode(value)
        data.append(0x0A)
        return data
    }

    public static func decode<T: Decodable>(_ type: T.Type, from data: Data) throws -> T {
        try JSONDecoder().decode(type, from: data)
    }
}
