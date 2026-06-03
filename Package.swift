// swift-tools-version: 6.0

import PackageDescription

let package = Package(
    name: "ClippingOpsCockpit",
    platforms: [
        .macOS(.v14)
    ],
    products: [
        .executable(name: "ClippingOpsCockpit", targets: ["ClippingOpsCockpit"])
    ],
    targets: [
        .executableTarget(
            name: "ClippingOpsCockpit",
            path: "Sources/ClippingOpsCockpit",
            exclude: ["Support/ClippingOpsCockpit.entitlements"]
        )
    ]
)
