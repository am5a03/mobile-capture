import Darwin
import Foundation

nonisolated struct CaptureDoctorCLIOptions: Sendable {
    enum Platform: String, Sendable { case android, iphone, simulator }
    enum Sources: String, Sendable {
        case network, logs, both = "network,logs"
        var network: Bool { self != .logs }
        var logs: Bool { self != .network }
    }
    let platform: Platform
    let sources: Sources
    let outputDirectory: URL

    init(arguments: [String]) throws {
        guard arguments.first == "doctor" else { throw AppError("Expected doctor --json --platform android|iphone|simulator.") }
        var fields: [String: String] = [:]
        var json = false
        var index = 1
        while index < arguments.count {
            let option = arguments[index]
            if option == "--json" {
                guard !json else { throw AppError("Doctor options must not be repeated.") }
                json = true
                index += 1
            } else {
                guard ["--platform", "--sources", "--output-directory"].contains(option), fields[option] == nil,
                      index + 1 < arguments.count else { throw AppError("Doctor received an unknown, repeated or incomplete option.") }
                fields[option] = arguments[index + 1]
                index += 2
            }
        }
        guard json, let value = fields["--platform"], let platform = Platform(rawValue: value),
              let sources = Sources(rawValue: fields["--sources"] ?? "network") else {
            throw AppError("Doctor requires --json, a supported --platform and --sources network|logs|network,logs.")
        }
        let directory = fields["--output-directory"]
        guard directory.map({ $0.hasPrefix("/") && !$0.contains("\0") }) ?? true else {
            throw AppError("Doctor output directories must be absolute paths.")
        }
        self.platform = platform
        self.sources = sources
        outputDirectory = directory.map { URL(fileURLWithPath: $0).standardizedFileURL } ?? CaptureSessionRegistry.defaultRoot
    }
}

nonisolated struct CaptureDoctorCLIEnvelope: Encodable, Sendable {
    struct Failure: Encodable, Sendable { let code: String; let message: String }
    struct DeviceSetup: Encodable, Sendable {
        let status = "notChecked"
        let manualActions: [String]
    }
    let options: CaptureDoctorCLIOptions?
    let application: URL?
    let report: CaptureDoctorReport?
    let error: Failure?

    private enum CodingKeys: String, CodingKey {
        case schemaVersion, command, scope, platform, captureNetwork, captureLogs, appPath, checkedAt
        case macPrerequisitesReady, checks, repairs, deviceSetup, error
    }

    func encode(to encoder: any Encoder) throws {
        var values = encoder.container(keyedBy: CodingKeys.self)
        try values.encode(1, forKey: .schemaVersion)
        try values.encode("doctor", forKey: .command)
        try values.encode("macPrerequisites", forKey: .scope)
        try values.encode(options?.platform.rawValue, forKey: .platform)
        try values.encode(options?.sources.network ?? true, forKey: .captureNetwork)
        try values.encode(options?.sources.logs ?? false, forKey: .captureLogs)
        try values.encode(application?.path, forKey: .appPath)
        try values.encode(report?.checkedAt, forKey: .checkedAt)
        try values.encode(report?.isReady, forKey: .macPrerequisitesReady)
        try values.encode(report?.rows ?? [], forKey: .checks)
        try values.encode(report?.repairs ?? [], forKey: .repairs)
        var actions: [String] = []
        switch options?.platform {
        case .android:
            actions.append("Connect and unlock the Android phone, enable USB debugging, and approve this Mac on the phone.")
        case .iphone:
            actions.append("Connect and unlock the iPhone and approve Trust This Computer on the phone.")
        case .simulator:
            actions.append("Choose and boot the intended simulator in Xcode before capture.")
        case nil: break
        }
        if options?.sources.network == true {
            if options?.platform == .iphone {
                actions.append("Import the app's phone profile in WireGuard and turn its tunnel on manually when capture requests it. Turn the tunnel off manually before confirming capture stop.")
                actions.append("Install this Mac's capture certificate on the iPhone and enable full trust in Certificate Trust Settings before HTTPS capture.")
            } else {
                actions.append("Complete the app's device network setup and certificate installation and trust steps manually before HTTPS capture.")
            }
        }
        if options?.sources.logs == true {
            actions.append("Choose the intended app and log scope and confirm device access in the app before log capture.")
        }
        try values.encode(DeviceSetup(manualActions: actions), forKey: .deviceSetup)
        try values.encode(error, forKey: .error)
    }

    func json() throws -> Data {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        var data = try encoder.encode(self)
        data.append(10)
        return data
    }
}

nonisolated enum CaptureDoctorCLI {
    struct Result: Sendable {
        let envelope: CaptureDoctorCLIEnvelope
        let exitCode: Int32
    }

    static func run(arguments: [String], executableURL: URL? = nil,
                    service: CaptureDoctorService = CaptureDoctorService(applicationBundle: nil)) async -> Result {
        let options: CaptureDoctorCLIOptions
        do { options = try CaptureDoctorCLIOptions(arguments: arguments) }
        catch {
            return Result(envelope: CaptureDoctorCLIEnvelope(options: nil, application: nil, report: nil,
                error: .init(code: "invalidArguments", message: error.localizedDescription)), exitCode: 64)
        }
        let application: URL
        do { application = try owningApplication(executableURL ?? runningExecutable()) }
        catch {
            return Result(envelope: CaptureDoctorCLIEnvelope(options: options, application: nil, report: nil,
                error: .init(code: "owningApplication", message: error.localizedDescription)), exitCode: 70)
        }
        var doctor = service
        doctor.applicationBundle = application
        let report = await doctor.inspect(CaptureDoctorRequest(platform: options.platform.rawValue,
            captureLogs: options.sources.logs, captureNetwork: options.sources.network, outputDirectory: options.outputDirectory))
        return Result(envelope: CaptureDoctorCLIEnvelope(options: options, application: application, report: report, error: nil),
            exitCode: report.isReady ? 0 : 10)
    }

    static func runningExecutable() throws -> URL {
        var count: UInt32 = 0
        _ = _NSGetExecutablePath(nil, &count)
        guard count > 0, count <= 1_048_576 else { throw AppError("The running host executable could not be resolved.") }
        var buffer = [CChar](repeating: 0, count: Int(count))
        guard _NSGetExecutablePath(&buffer, &count) == 0 else { throw AppError("The running host executable could not be resolved.") }
        let path = String(decoding: buffer.prefix { $0 != 0 }.map { UInt8(bitPattern: $0) }, as: UTF8.self)
        return URL(fileURLWithPath: path).standardizedFileURL.resolvingSymlinksInPath()
    }

    static func owningApplication(_ executable: URL) throws -> URL {
        func isExecutableFile(_ file: URL) -> Bool {
            var info = stat()
            return stat(file.path, &info) == 0 && info.st_mode & S_IFMT == S_IFREG
                && FileManager.default.isExecutableFile(atPath: file.path)
        }
        let host = executable.standardizedFileURL.resolvingSymlinksInPath()
        let macOS = host.deletingLastPathComponent()
        let contents = macOS.deletingLastPathComponent()
        let application = contents.deletingLastPathComponent()
        guard host.lastPathComponent == "mobile-capture-host", macOS.lastPathComponent == "MacOS",
              contents.lastPathComponent == "Contents", application.pathExtension == "app",
              isExecutableFile(host),
              let data = try? Data(contentsOf: contents.appendingPathComponent("Info.plist")),
              let info = try? PropertyListSerialization.propertyList(from: data, format: nil) as? [String: Any],
              info["MobileCaptureCompanion"] as? Bool == true, info["CFBundlePackageType"] as? String == "APPL",
              let identifier = info["CFBundleIdentifier"] as? String, !identifier.isEmpty,
              let mainName = info["CFBundleExecutable"] as? String, !mainName.isEmpty,
              !mainName.contains("/"), !mainName.contains("\0"), ![".", ".."].contains(mainName),
              let versions = info["MobileCaptureHandoffVersions"] as? [Int], versions.contains(1) else {
            throw AppError("Doctor must run from a complete Mobile Capture companion app with its expected metadata.")
        }
        let main = macOS.appendingPathComponent(mainName).resolvingSymlinksInPath()
        guard main.deletingLastPathComponent() == macOS, isExecutableFile(main) else {
            throw AppError("The owning Mobile Capture app is missing its application executable.")
        }
        return application
    }
}
