import AppKit
import Observation
import Sparkle

@MainActor
@Observable
final class MobileCaptureUpdater: NSObject, SPUUpdaterDelegate {
    private let store: CaptureStore
    private let configuration: CaptureUpdateConfiguration?
    private(set) var status: String?
    private var preferenceRevision = 0
    @ObservationIgnored private var controller: SPUStandardUpdaterController?
    @ObservationIgnored private var observations: [NSKeyValueObservation] = []

    init(store: CaptureStore, bundle: Bundle = .main) {
        self.store = store
        configuration = CaptureUpdateConfiguration(info: bundle.infoDictionary ?? [:], bundleIdentifier: bundle.bundleIdentifier)
        super.init()
        guard configuration != nil else { return }
        let controller = SPUStandardUpdaterController(startingUpdater: false, updaterDelegate: self, userDriverDelegate: nil)
        self.controller = controller
        observations = [controller.updater.observe(\.automaticallyChecksForUpdates) { [weak self] _, _ in
            MainActor.assumeIsolated { self?.preferenceRevision += 1 }
        }, controller.updater.observe(\.canCheckForUpdates) { [weak self] _, _ in
            MainActor.assumeIsolated { self?.preferenceRevision += 1 }
        }]
        do { try controller.updater.start() }
        catch { status = error.localizedDescription; self.controller = nil }
    }

    var isEnabled: Bool { controller != nil }
    var releaseTag: String? { configuration?.releaseTag }
    var automaticallyChecksForUpdates: Bool {
        get { _ = preferenceRevision; return controller?.updater.automaticallyChecksForUpdates ?? false }
        set { controller?.updater.automaticallyChecksForUpdates = newValue }
    }
    var canCheck: Bool {
        _ = preferenceRevision
        return controller?.updater.canCheckForUpdates == true && store.updateBlocker == nil
    }
    var explanation: String {
        if let status { return status }
        if !isEnabled { return "Updates are available in packaged beta releases." }
        switch store.updateAdmission.state {
        case .checking: return "Finish or cancel the update to continue capture work."
        case .installationCommitted: return "Restart Mobile Capture to continue capture work, including after closing or cancelling the prepared update."
        case .available:
            if let blocker = store.updateBlocker { return blocker.localizedDescription }
            if let version = store.updateAdmission.pendingVersion { return "Version \(version) is available. Choose Check for Updates to install it." }
            return "Updates install only when you choose. Captures and device setup must finish first."
        }
    }

    func checkForUpdates() {
        guard let controller, controller.updater.canCheckForUpdates else { return }
        do {
            if store.updateAdmission.allowsCaptureWork {
                try store.updateAdmission.begin(blocker: store.updateBlocker, otherInstance: hasOtherInstance)
            } else {
                try store.updateAdmission.validate(blocker: store.updateBlocker, otherInstance: hasOtherInstance)
            }
            status = nil
            controller.checkForUpdates(nil)
        } catch { status = error.localizedDescription }
    }

    private var hasOtherInstance: Bool { Self.otherRunningInstance() != nil }

    static func otherRunningInstance() -> NSRunningApplication? {
        let target = Bundle.main.bundleURL.resolvingSymlinksInPath().standardizedFileURL
        return NSWorkspace.shared.runningApplications.first {
            $0.processIdentifier != ProcessInfo.processInfo.processIdentifier
                && $0.bundleURL?.resolvingSymlinksInPath().standardizedFileURL == target
        }
    }

    func feedURLString(for updater: SPUUpdater) -> String? { configuration?.feedURL.absoluteString }
    func allowedChannels(for updater: SPUUpdater) -> Set<String> { configuration.map { [$0.channel] } ?? [] }

    func updater(_ updater: SPUUpdater, mayPerform updateCheck: SPUUpdateCheck) throws {
        if updateCheck == .updates {
            try store.updateAdmission.validate(blocker: store.updateBlocker, otherInstance: hasOtherInstance)
        }
    }

    func updater(_ updater: SPUUpdater, shouldProceedWithUpdate updateItem: SUAppcastItem, updateCheck: SPUUpdateCheck) throws {
        try store.updateAdmission.shouldProceed(version: updateItem.displayVersionString, manual: updateCheck == .updates,
            blocker: store.updateBlocker, otherInstance: hasOtherInstance)
    }

    func updater(_ updater: SPUUpdater, userDidMake choice: SPUUserUpdateChoice, forUpdate updateItem: SUAppcastItem, state: SPUUserUpdateState) {
        if state.stage == .installing { store.updateAdmission.commitInstallation() }
    }

    func updaterDidNotFindUpdate(_ updater: SPUUpdater) { store.updateAdmission.noUpdateFound() }

    func updater(_ updater: SPUUpdater, didExtractUpdate item: SUAppcastItem) {
        // The standard ready dialog bypasses userDidMakeChoice and can leave install-on-quit armed.
        store.updateAdmission.commitInstallation()
    }

    func updater(_ updater: SPUUpdater, willInstallUpdate item: SUAppcastItem) {
        store.updateAdmission.commitInstallation()
    }

    func updater(_ updater: SPUUpdater, didFinishUpdateCycleFor updateCheck: SPUUpdateCheck, error: (any Error)?) {
        if updateCheck == .updates { store.updateAdmission.cycleFinished() }
    }
}
