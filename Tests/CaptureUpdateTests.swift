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
        #expect(throws: (any Error).self) { try CaptureUpdateOwnershipLease(directory: fixture.lock) }
        #expect(try Data(contentsOf: fixture.owner).isEmpty)
        admission.cycleFinished()
        #expect(admission.allowsCaptureWork)
        let next = try CaptureUpdateOwnershipLease(directory: fixture.lock)
        withExtendedLifetime(next) {}
    }

    @Test func `installation commitment survives cycle completion and cancellation`() throws {
        let fixture = try UpdateFixture()
        defer { fixture.remove() }
        let admission = CaptureUpdateAdmission()
        try admission.begin(blocker: nil, otherInstance: false, lockDirectory: fixture.lock)
        admission.commitInstallation()
        admission.cycleFinished()
        #expect(admission.state == .installationCommitted)
        #expect(!admission.allowsCaptureWork)
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
