import Darwin
import Foundation
import Observation

enum CaptureUpdateBlocker: String, Error, LocalizedError {
    case capture = "Finish the capture and restore its connection before checking for updates."
    case save = "Finish saving the capture, or retry its unfinished ZIP, before checking for updates."
    case operation = "Wait for the current capture, setup or Doctor operation to finish before checking for updates."
    case otherInstance = "Quit the other running copy of this app before checking for updates."
    case ownership = "Capture ownership needs recovery. Open the previous session and restore its connection before checking for updates."
    case updating = "Finish or cancel the update before starting capture work."

    var errorDescription: String? { rawValue }
}

@MainActor
@Observable
final class CaptureUpdateAdmission {
    enum State { case available, checking, installationCommitted }
    private(set) var state = State.available
    @ObservationIgnored private var lease: CaptureUpdateOwnershipLease?

    var allowsCaptureWork: Bool { state == .available }

    func begin(blocker: CaptureUpdateBlocker?, otherInstance: Bool, lockDirectory: URL? = nil) throws {
        guard allowsCaptureWork else { throw CaptureUpdateBlocker.updating }
        if let blocker { throw blocker }
        guard !otherInstance else { throw CaptureUpdateBlocker.otherInstance }
        lease = try CaptureUpdateOwnershipLease(directory: lockDirectory)
        state = .checking
    }

    func validate(blocker: CaptureUpdateBlocker?, otherInstance: Bool) throws {
        guard state == .checking, lease != nil else { throw CaptureUpdateBlocker.updating }
        if let blocker { throw blocker }
        guard !otherInstance else { throw CaptureUpdateBlocker.otherInstance }
    }

    func commitInstallation() {
        guard state == .checking else { return }
        state = .installationCommitted
    }

    func cycleFinished() {
        guard state == .checking else { return }
        lease = nil
        state = .available
    }
}

/// Keeps the host's existing inode locked without claiming or rewriting its session record.
final class CaptureUpdateOwnershipLease {
    private let descriptor: Int32

    init(directory: URL? = nil) throws {
        let directory = directory ?? URL(fileURLWithPath: "/tmp/capture-companion-\(getuid())", isDirectory: true)
        if mkdir(directory.path, 0o700) != 0, errno != EEXIST { throw CaptureUpdateBlocker.ownership }
        let parent = open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard parent >= 0 else { throw CaptureUpdateBlocker.ownership }
        defer { close(parent) }
        var root = stat()
        guard fstat(parent, &root) == 0, root.st_uid == geteuid(), root.st_mode & 0o777 == 0o700 else {
            throw CaptureUpdateBlocker.ownership
        }
        let fd = openat(parent, "owner.lock", O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK, 0o600)
        guard fd >= 0 else { throw CaptureUpdateBlocker.ownership }
        var accepted = false
        defer { if !accepted { close(fd) } }
        var info = stat(), pathInfo = stat()
        guard fstat(fd, &info) == 0, info.st_mode & S_IFMT == S_IFREG, info.st_uid == geteuid(),
              info.st_mode & 0o022 == 0, info.st_nlink == 1, info.st_size <= 4096,
              flock(fd, LOCK_EX | LOCK_NB) == 0,
              fstatat(parent, "owner.lock", &pathInfo, AT_SYMLINK_NOFOLLOW) == 0,
              pathInfo.st_dev == info.st_dev, pathInfo.st_ino == info.st_ino else {
            throw CaptureUpdateBlocker.ownership
        }
        let data = try FileHandle(fileDescriptor: fd, closeOnDealloc: false).readToEnd() ?? Data()
        guard data.count <= 4096, let record = String(data: data, encoding: .utf8) else { throw CaptureUpdateBlocker.ownership }
        let path = record.trimmingCharacters(in: .whitespacesAndNewlines)
        if !path.isEmpty {
            guard path.hasPrefix("/"), !path.contains("\0"), URL(fileURLWithPath: path).standardizedFileURL.path == path else {
                throw CaptureUpdateBlocker.ownership
            }
            let metadata = open(URL(fileURLWithPath: path).appendingPathComponent("session.json").path, O_RDONLY | O_NOFOLLOW | O_CLOEXEC | O_NONBLOCK)
            guard metadata >= 0 else { throw CaptureUpdateBlocker.ownership }
            let handle = FileHandle(fileDescriptor: metadata, closeOnDealloc: true)
            defer { try? handle.close() }
            var stateInfo = stat()
            guard fstat(metadata, &stateInfo) == 0, stateInfo.st_mode & S_IFMT == S_IFREG,
                  stateInfo.st_uid == geteuid(), stateInfo.st_mode & 0o022 == 0,
                  stateInfo.st_nlink == 1, stateInfo.st_size <= 4 * 1024 * 1024 else { throw CaptureUpdateBlocker.ownership }
            let decoder = JSONDecoder()
            decoder.keyDecodingStrategy = .convertFromSnakeCase
            guard let bytes = try handle.readToEnd(), let session = try? decoder.decode(CaptureSession.self, from: bytes),
                  ["saved", "partial", "failed"].contains(session.phase), session.routingRestored == true,
                  !session.canFinalize, URL(fileURLWithPath: session.directory).standardizedFileURL.path == path else {
                throw CaptureUpdateBlocker.ownership
            }
        }
        descriptor = fd
        accepted = true
    }

    deinit { close(descriptor) }
}
