// swift-tools-version: 5.9

import PackageDescription

let package = Package(
    name: "MultiTimer",
    defaultLocalization: "en",
    platforms: [.macOS(.v13), .iOS("18.0")],
    products: [
        .library(name: "MultiTimerCore", targets: ["MultiTimerCore"]),
        .executable(name: "MultiTimer", targets: ["MultiTimer"]),
        .executable(name: "MultiTimerCLI", targets: ["MultiTimerCLI"]),
    ],
    dependencies: [
        .package(url: "https://github.com/sindresorhus/KeyboardShortcuts", exact: "0.7.1"),
        .package(url: "https://github.com/sindresorhus/LaunchAtLogin", exact: "5.0.2"),
    ],
    targets: [
        .target(name: "MultiTimerCore", path: "MultiTimerCore"),
        .executableTarget(
            name: "MultiTimer",
            dependencies: [
                "MultiTimerCore",
                "KeyboardShortcuts",
                "LaunchAtLogin",
            ],
            path: "MultiTimer",
            resources: [.process("Resources")]
        ),
        .executableTarget(
            name: "MultiTimerCLI",
            dependencies: ["MultiTimerCore"],
            path: "MultiTimerCLI"
        ),
        .testTarget(
            name: "MultiTimerCoreTests",
            dependencies: ["MultiTimerCore"],
            path: "Tests/MultiTimerCoreTests"
        ),
    ]
)
