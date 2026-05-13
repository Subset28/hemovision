import PackageDescription

let package = Package(
    name: "OmniSightKit",
    platforms: [
        .iOS(.v16)
    ],
    products: [
        .library(
            name: "OmniSightKit",
            targets: ["OmniSightKit"]),
    ],
    targets: [
        .target(
            name: "OmniSightKit",
            dependencies: []),
    ]
)
