// swift-tools-version: 6.0
import PackageDescription

let package = Package(
    name: "TravelCore",
    defaultLocalization: "en",
    platforms: [.iOS(.v17), .macOS(.v14)],
    products: [.library(name: "TravelCore", targets: ["TravelCore"])],
    targets: [
        .target(name: "TravelCore", resources: [.process("Resources")]),
        .testTarget(name: "TravelCoreTests", dependencies: ["TravelCore"])
    ]
)
