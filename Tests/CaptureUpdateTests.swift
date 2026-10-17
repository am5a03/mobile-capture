import Darwin
import Foundation
import Testing
@testable import CaptureSetupStoreKit

@MainActor
struct CaptureUpdateTests {
    @Test func `a manual check holds one unchanged ownership inode until the cycle aborts`() throws {
        let fixture = try UpdateFixture()
        defer { fixture.remove() }
        let admission = CaptureUpdateAdmission()
        try admission.begin(blocker: nil, otherInstance: false, lockDirectory: fixture.lock)
        #expect(!admission.allowsCaptureWork)
        try admission.validate(blocker: nil, otherInstance: false)
        #expect(throws: CaptureUpdateBlocker.self) { try admission.begin(blocker: nil, otherInstance: false, lockDirectory: fixture.lock) }
        #expect(throws: (any Error).self) { try CaptureUpdateOwnershipLease(directory: fixture.lock) }
        #expect(try Data(contentsOf: fixture.owner).isEmpty)
        admission.cycleFinished()
        #expect(admission.allowsCaptureWork)
        let next = try CaptureUpdateOwnershipLease(directory: fixture.lock)
        withExtendedLifetime(next) {}
    }

    @Test func `extraction commitment retains ownership through a nil error cycle and refuses more work`() throws {
        let fixture = try UpdateFixture()
        defer { fixture.remove() }
        let admission = CaptureUpdateAdmission()
        try admission.begin(blocker: nil, otherInstance: false, lockDirectory: fixture.lock)
        admission.commitInstallation()
        admission.cycleFinished()
        try admission.validate(blocker: nil, otherInstance: false)
        #expect(admission.state == .installationCommitted)
        #expect(!admission.allowsCaptureWork)
        let owner = CaptureStore(updateAdmission: admission)
        owner.showSetup()
        owner.showDoctor()
        #expect(!owner.isSetupPresented && !owner.isDoctorPresented && !owner.canStart)
        #expect(throws: (any Error).self) { try CaptureUpdateOwnershipLease(directory: fixture.lock) }
    }

    @Test func `busy work and a second instance refuse admission before creating ownership`() throws {
        let fixture = try UpdateFixture()
        defer { fixture.remove() }
        let admission = CaptureUpdateAdmission()
        for blocker in [CaptureUpdateBlocker.capture, .save, .operation] {
            #expect(throws: CaptureUpdateBlocker.self) { try admission.begin(blocker: blocker, otherInstance: false, lockDirectory: fixture.lock) }
        }
        #expect(throws: CaptureUpdateBlocker.self) { try admission.begin(blocker: nil, otherInstance: true, lockDirectory: fixture.lock) }
        #expect(!FileManager.default.fileExists(atPath: fixture.owner.path))
    }

    @Test func `saved legacy ownership is admitted without rewriting its bytes`() throws {
        let fixture = try UpdateFixture()
        defer { fixture.remove() }
        try fixture.record(phase: "saved", restored: true, package: true)
        let bytes = try Data(contentsOf: fixture.owner)
        let lease = try CaptureUpdateOwnershipLease(directory: fixture.lock)
        #expect(try Data(contentsOf: fixture.owner) == bytes)
        withExtendedLifetime(lease) {}
    }

    @Test(arguments: [("recording", true, true), ("saved", false, true), ("partial", true, false), ("unknown", true, true)])
    func `active recovery retry and unknown ownership remain blocked`(state: (String, Bool, Bool)) throws {
        let fixture = try UpdateFixture()
        defer { fixture.remove() }
        try fixture.record(phase: state.0, restored: state.1, package: state.2)
        #expect(throws: CaptureUpdateBlocker.self) { try CaptureUpdateOwnershipLease(directory: fixture.lock) }
    }

    @Test func `unsafe lock modes symlinks hardlinks and unresolved records are blocked`() throws {
        let fixture = try UpdateFixture()
        defer { fixture.remove() }
        try FileManager.default.createDirectory(at: fixture.lock, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        try Data("/missing/session".utf8).write(to: fixture.owner)
        #expect(throws: CaptureUpdateBlocker.self) { try CaptureUpdateOwnershipLease(directory: fixture.lock) }
        try Data().write(to: fixture.owner)
        #expect(chmod(fixture.owner.path, 0o666) == 0)
        #expect(throws: CaptureUpdateBlocker.self) { try CaptureUpdateOwnershipLease(directory: fixture.lock) }
        #expect(chmod(fixture.owner.path, 0o600) == 0)
        let alias = fixture.root.appendingPathComponent("alias")
        #expect(link(fixture.owner.path, alias.path) == 0)
        #expect(throws: CaptureUpdateBlocker.self) { try CaptureUpdateOwnershipLease(directory: fixture.lock) }
        try FileManager.default.removeItem(at: fixture.owner)
        try FileManager.default.createSymbolicLink(at: fixture.owner, withDestinationURL: alias)
        #expect(throws: CaptureUpdateBlocker.self) { try CaptureUpdateOwnershipLease(directory: fixture.lock) }
    }
    @Test func `a separate process holding the host lock prevents update admission`() throws {
        let fixture = try UpdateFixture()
        defer { fixture.remove() }
        try FileManager.default.createDirectory(at: fixture.lock, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let child = Process()
        child.executableURL = URL(fileURLWithPath: "/usr/bin/python3")
        child.arguments = ["-c", "import fcntl,os,sys; f=open(sys.argv[1],'w'); os.chmod(sys.argv[1],0o600); fcntl.flock(f,fcntl.LOCK_EX); sys.stdout.write('R'); sys.stdout.flush(); sys.stdin.read(1)", fixture.owner.path]
        let ready = Pipe(), release = Pipe()
        child.standardOutput = ready
        child.standardInput = release
        try child.run()
        defer {
            try? release.fileHandleForWriting.close()
            child.waitUntilExit()
        }
        #expect(try ready.fileHandleForReading.read(upToCount: 1) == Data("R".utf8))
        let admission = CaptureUpdateAdmission()
        #expect(throws: CaptureUpdateBlocker.self) { try admission.begin(blocker: nil, otherInstance: false, lockDirectory: fixture.lock) }
        #expect(admission.allowsCaptureWork)
        try release.fileHandleForWriting.write(contentsOf: Data("X".utf8))
        child.waitUntilExit()
        try admission.begin(blocker: nil, otherInstance: false, lockDirectory: fixture.lock)
        #expect(!admission.allowsCaptureWork)
        admission.cycleFinished()
    }

    @Test func `background discovery records availability without blocking capture or acquiring ownership`() throws {
        let fixture = try UpdateFixture()
        defer { fixture.remove() }
        let admission = CaptureUpdateAdmission()
        #expect(throws: (any Error).self) {
            try admission.shouldProceed(version: "0.2.0", manual: false, blocker: .capture, otherInstance: true)
        }
        #expect(admission.pendingVersion == "0.2.0" && admission.allowsCaptureWork)
        #expect(!FileManager.default.fileExists(atPath: fixture.owner.path))
        try admission.begin(blocker: nil, otherInstance: false, lockDirectory: fixture.lock)
        try admission.shouldProceed(version: "0.2.0", manual: true, blocker: nil, otherInstance: false)
        #expect(admission.pendingVersion == nil)
        #expect(throws: CaptureUpdateBlocker.self) {
            try admission.shouldProceed(version: "0.2.0", manual: true, blocker: .operation, otherInstance: false)
        }
        admission.cycleFinished()
        #expect(admission.allowsCaptureWork)
        #expect(throws: (any Error).self) { try admission.shouldProceed(version: "0.3.0", manual: false, blocker: nil, otherInstance: false) }
        admission.noUpdateFound()
        #expect(admission.pendingVersion == nil)
    }

    @Test func `direct and nested work is refused during a check and usable after early cancellation`() async throws {
        let fixture = try UpdateWorkFixture()
        defer { fixture.remove() }
        let owner = fixture.store()
        let nested = owner.makeSetupCheck()
        #expect(nested.updateAdmission === owner.updateAdmission)
        #expect(owner.canStart && nested.canStart)
        try owner.updateAdmission.begin(blocker: owner.updateBlocker, otherInstance: false, lockDirectory: fixture.root.appendingPathComponent("lock"))
        await owner.start()
        await nested.start()
        await owner.refreshDevices(includeApplications: false)
        await nested.refreshDevices(includeApplications: false)
        await owner.setup.startCheck(owner)
        await owner.setup.prepareAndroidCertificate(owner)
        await owner.setup.inspect(owner)
        await owner.doctor.refresh(owner)
        await owner.doctor.prepareRepair(.installIPhoneUSBTools, owner: owner)
        owner.doctor.beginRepair(owner)
        #expect(owner.session == nil && nested.session == nil)
        #expect(owner.setup.checkCapture == nil && owner.setup.report == nil)
        #expect(owner.doctor.report == nil && owner.doctor.preview == nil)
        #expect(await fixture.discovery.calls == 0)
        #expect(!FileManager.default.fileExists(atPath: fixture.commands.path))
        owner.updateAdmission.cycleFinished()
        #expect(owner.canStart && nested.canStart)
        await owner.start()
        #expect(owner.session?.phase == "recording", "\(owner.error ?? "No start error")")
        #expect(try fixture.readCommands().contains("start"))
        #expect(owner.updateBlocker == .capture)
        #expect(throws: CaptureUpdateBlocker.self) {
            try owner.updateAdmission.begin(blocker: owner.updateBlocker, otherInstance: false, lockDirectory: fixture.root.appendingPathComponent("lock"))
        }
        let before = try fixture.readCommands()
        try owner.updateAdmission.begin(blocker: nil, otherInstance: false, lockDirectory: fixture.root.appendingPathComponent("lock"))
        owner.markerText = "must not be written"
        await owner.addMarker()
        await owner.stop()
        #expect(!owner.isAddingMarker && owner.markerReceipt == nil)
        #expect(try fixture.readCommands() == before)
        owner.updateAdmission.cycleFinished()
        await owner.stop()
        #expect(owner.session?.routingRestored == true && !owner.hasActiveCapture)
    }

    @Test func `in flight nested discovery wins admission even before capture starts`() async throws {
        let fixture = try UpdateWorkFixture()
        defer { fixture.remove() }
        let owner = fixture.store()
        let child = owner.makeSetupCheck()
        await fixture.discovery.suspend()
        let operation = Task { await child.refreshDevices(includeApplications: false) }
        for _ in 0..<200 {
            if await fixture.discovery.calls > 0 { break }
            try await Task.sleep(for: .milliseconds(5))
        }
        #expect(child.updateBlocker == .operation)
        #expect(throws: CaptureUpdateBlocker.self) {
            try owner.updateAdmission.begin(blocker: child.updateBlocker, otherInstance: false, lockDirectory: fixture.root.appendingPathComponent("lock"))
        }
        await fixture.discovery.resume()
        await operation.value
        #expect(child.updateBlocker == nil)
        try owner.updateAdmission.begin(blocker: child.updateBlocker, otherInstance: false, lockDirectory: fixture.root.appendingPathComponent("lock"))
        await child.refreshDevices(includeApplications: false)
        #expect(await fixture.discovery.calls == 1)
        owner.updateAdmission.cycleFinished()
    }

    @Test func `Doctor checking blocks admission and its repair entry respects an admitted update`() async throws {
        let fixture = try UpdateWorkFixture()
        defer { fixture.remove() }
        let runner = UpdateDoctorProbe()
        let doctor = CaptureDoctorStore(service: CaptureDoctorService(applicationBundle: nil, runner: runner, homeDirectory: fixture.root, trustedExternalRoots: [fixture.root], architecture: "arm64"))
        let owner = fixture.store(doctor: doctor)
        owner.captureNetwork = false
        owner.captureLogs = true
        owner.adbPath = fixture.host.path
        let checking = Task { await doctor.refresh(owner) }
        for _ in 0..<200 {
            if await runner.calls > 0 { break }
            try await Task.sleep(for: .milliseconds(5))
        }
        #expect(doctor.isChecking && owner.updateBlocker == .operation)
        #expect(throws: CaptureUpdateBlocker.self) {
            try owner.updateAdmission.begin(blocker: owner.updateBlocker, otherInstance: false, lockDirectory: fixture.root.appendingPathComponent("lock"))
        }
        await runner.release()
        await checking.value
        await doctor.prepareRepair(.installIPhoneUSBTools, owner: owner)
        #expect(doctor.preview?.canRun == true)
        let count = await runner.calls
        try owner.updateAdmission.begin(blocker: owner.updateBlocker, otherInstance: false, lockDirectory: fixture.root.appendingPathComponent("lock"))
        doctor.beginRepair(owner)
        #expect(!doctor.isRepairing)
        #expect(await runner.calls == count)
        owner.updateAdmission.cycleFinished()
    }

    @Test func `the parent snapshot includes a live setup child and its unfinished ZIP`() async throws {
        let fixture = try UpdateWorkFixture()
        defer { fixture.remove() }
        let owner = fixture.store()
        await owner.setup.startCheck(owner)
        let nested = try #require(owner.setup.checkCapture)
        #expect(nested.updateAdmission === owner.updateAdmission)
        #expect(nested.session?.phase == "recording", "\(owner.setup.error ?? nested.error ?? "No setup error")")
        #expect(owner.updateBlocker == .capture)
        #expect(throws: CaptureUpdateBlocker.self) {
            try owner.updateAdmission.begin(blocker: owner.updateBlocker, otherInstance: false, lockDirectory: fixture.root.appendingPathComponent("lock"))
        }
        await owner.setup.stopCheck()
        #expect(owner.updateBlocker == nil)
        let directory = URL(fileURLWithPath: try #require(nested.session?.directory))
        let metadata = directory.appendingPathComponent("session.json")
        var state = try #require(JSONSerialization.jsonObject(with: Data(contentsOf: metadata)) as? [String: Any])
        state["phase"] = "partial"
        state.removeValue(forKey: "package_path")
        try JSONSerialization.data(withJSONObject: state).write(to: metadata)
        await nested.loadSession(at: directory)
        #expect(owner.updateBlocker == .save)
        #expect(throws: CaptureUpdateBlocker.self) {
            try owner.updateAdmission.begin(blocker: owner.updateBlocker, otherInstance: false, lockDirectory: fixture.root.appendingPathComponent("lock"))
        }
    }

    @Test func `sealed beta policy rejects insecure or incomplete metadata`() {
        let valid: [String: Any] = ["CaptureDistributionUpdatesEnabled": true, "CFBundleIdentifier": "local.mobilecapture.development",
            "CaptureUpdateChannel": "beta", "CaptureBetaReleaseTag": "v0.1.2-beta.1", "SUFeedURL": "https://example.test/appcast.xml",
            "SUPublicEDKey": Data(repeating: 1, count: 32).base64EncodedString(), "SUEnableAutomaticChecks": false,
            "SUAllowsAutomaticUpdates": false, "SUAutomaticallyUpdate": false, "SURequireSignedFeed": true,
            "SUVerifyUpdateBeforeExtraction": true, "SUSendProfileInfo": false]
        #expect(CaptureUpdateConfiguration(info: valid, bundleIdentifier: "local.mobilecapture.development") != nil)
        for (key, value) in [("SUFeedURL", "http://example.test/feed"), ("SUPublicEDKey", "bad"), ("CaptureUpdateChannel", "stable"), ("CaptureBetaReleaseTag", "v0.1.2"), ("CFBundleIdentifier", "other.bundle")] {
            var invalid = valid
            invalid[key] = value
            #expect(CaptureUpdateConfiguration(info: invalid, bundleIdentifier: "local.mobilecapture.development") == nil)
        }
        for key in ["SURequireSignedFeed", "SUVerifyUpdateBeforeExtraction"] {
            var invalid = valid
            invalid[key] = false
            #expect(CaptureUpdateConfiguration(info: invalid, bundleIdentifier: "local.mobilecapture.development") == nil)
        }
    }

}

private struct UpdateFixture {
    let root: URL
    var lock: URL { root.appendingPathComponent("ownership") }
    var owner: URL { lock.appendingPathComponent("owner.lock") }
    init() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("capture-update-\(UUID())")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
    }
    func remove() { try? FileManager.default.removeItem(at: root) }
    func record(phase: String, restored: Bool, package: Bool) throws {
        try FileManager.default.createDirectory(at: lock, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        let session = root.appendingPathComponent("session")
        try FileManager.default.createDirectory(at: session, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        var metadata: [String: Any] = ["id": "fixture", "directory": session.path, "platform": "android", "device_id": "fixture", "device_name": "Fixture", "started_at": "2026-10-16T00:00:00Z", "phase": phase, "routing_restored": restored]
        if package { metadata["package_path"] = session.appendingPathComponent("capture-package.zip").path }
        try JSONSerialization.data(withJSONObject: metadata).write(to: session.appendingPathComponent("session.json"))
        try Data(session.path.utf8).write(to: owner)
    }
}

private actor UpdateDiscoveryProbe {
    private(set) var calls = 0
    private var suspended = false
    private var waiter: CheckedContinuation<Void, Never>?
    func suspend() { suspended = true }
    func resume() { suspended = false; waiter?.resume(); waiter = nil }
    func run() async -> NativeCaptureDiscoveryResult {
        calls += 1
        if suspended { await withCheckedContinuation { waiter = $0 } }
        return Self.result
    }
    static var result: NativeCaptureDiscoveryResult {
        .init(devices: [.init(id: "synthetic", name: "Synthetic Android", platform: "android", state: "ready")], tools: [:], networkServices: [], warnings: [])
    }
}

private struct UpdateWorkFixture {
    let root: URL
    let discovery = UpdateDiscoveryProbe()
    var commands: URL { root.appendingPathComponent("commands") }
    var host: URL { root.appendingPathComponent("host") }
    init() throws {
        root = FileManager.default.temporaryDirectory.appendingPathComponent("update-work-\(UUID())")
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: false, attributes: [.posixPermissions: 0o700])
        try Data(Self.script.utf8).write(to: host)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: host.path)
        let bin = root.appendingPathComponent("bin")
        try FileManager.default.createDirectory(at: bin, withIntermediateDirectories: false)
        let brew = bin.appendingPathComponent("brew")
        try Data("Synthetic, never executed".utf8).write(to: brew)
        try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: brew.path)
    }
    func remove() { try? FileManager.default.removeItem(at: root) }
    func readCommands() throws -> [String] { try String(contentsOf: commands, encoding: .utf8).split(separator: "\n").map(String.init) }
    @MainActor func store(doctor: CaptureDoctorStore? = nil) -> CaptureStore {
        let inspector = CaptureSetupInspector(applicationBundle: nil, caDirectory: root.appendingPathComponent("ca"), iphoneProfileRoot: root.appendingPathComponent("profiles"), routingLockDirectory: root.appendingPathComponent("lock"), availableDiskBytes: { _ in 4_000_000_000 })
        let store = CaptureStore(hostExecutable: host, initialDiscovery: UpdateDiscoveryProbe.result, outputRoot: root.appendingPathComponent("sessions"), setupInspector: inspector, discover: { _ in await discovery.run() }, doctor: doctor)
        store.selectedDeviceID = "android:synthetic"
        return store
    }
    private static let script = #"""
    #!/usr/bin/python3
    import datetime,json,pathlib,sys
    root=pathlib.Path(__file__).parent
    command=sys.argv[1]
    with (root/'commands').open('a') as f: f.write(command+'\n')
    if command=='start':
        request=json.loads(pathlib.Path(sys.argv[3]).read_text())
        session=pathlib.Path(request['output_root'])/'session'
        for part in ('logs','network','timeline','setup','runtime'): (session/part).mkdir(parents=True,exist_ok=True)
        state={'id':'fixture','directory':str(session),'platform':'android','device_id':'synthetic','device_name':'Synthetic Android','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat().replace('+00:00','Z'),'phase':'recording','routing_restored':False}
    else: state=json.loads((root/'state.json').read_text())
    if command=='stop': state.update(phase='saved',routing_restored=True,package_path=str(pathlib.Path(state['directory'])/'capture.zip'))
    (root/'state.json').write_text(json.dumps(state))
    (pathlib.Path(state['directory'])/'session.json').write_text(json.dumps(state))
    print(json.dumps({'session':state}))
    """#
}

private actor UpdateDoctorProbe: CaptureDoctorCommandRunning {
    private(set) var calls = 0
    private var suspended = true
    private var waiter: CheckedContinuation<Void, Never>?
    func release() { suspended = false; waiter?.resume(); waiter = nil }
    func run(_ command: CaptureDoctorCommand, progress: @escaping @Sendable (String) -> Void) async throws -> CaptureDoctorCommandResult {
        calls += 1
        if suspended { await withCheckedContinuation { waiter = $0 } }
        return .init(exitCode: 0, stdout: "Android Debug Bridge version 1.0.41", stderr: "")
    }
}
