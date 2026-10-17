import SwiftUI

struct MobileCaptureSettingsView: View {
    @Bindable var store: CaptureStore
    @Bindable var updater: MobileCaptureUpdater
    var showCapture: () -> Void
    private let version = Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "Development"

    private let build = Bundle.main.object(forInfoDictionaryKey: "CFBundleVersion") as? String ?? "Unknown"

    var body: some View {
        Form {
            Section("Devices") {
                Text("Set up a new phone once, or check the components used by this Mac.")
                    .foregroundStyle(.secondary)
                HStack {
                    Button("Device Setup…", systemImage: "iphone") { store.showSetup(); showCapture() }
                    Button("Doctor…", systemImage: "stethoscope") { store.showDoctor(); showCapture() }
                }.disabled(!store.updateAdmission.allowsCaptureWork || store.hasActiveCapture || store.isBusy || store.doctor.isRepairing)
                Text("Phone certificate approval and iPhone full trust are completed on the phone. Setup includes a separate HTTPS connection check.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Saved Captures") {
                LabeledContent("Session Folder") {
                    Text(store.outputRoot.path).lineLimit(2).truncationMode(.middle).textSelection(.enabled)
                }
                Button("Choose Folder…") { store.chooseOutputRoot() }
                    .disabled(!store.updateAdmission.allowsCaptureWork || store.hasActiveCapture || store.isBusy || store.doctor.isRepairing)
                Text("Existing sessions, certificates and iPhone tunnel profiles stay in their current locations.")
                    .font(.caption).foregroundStyle(.secondary)
            }
            Section("Updates") {
                LabeledContent("Version", value: "\(version) (\(build))")
                if let tag = updater.releaseTag { LabeledContent("Beta Release", value: tag) }
                if updater.isEnabled {
                    Toggle("Automatically Check for Updates", isOn: $updater.automaticallyChecksForUpdates)
                        .toggleStyle(.checkbox)
                    Button("Check for Updates…") { updater.checkForUpdates() }
                        .disabled(!updater.canCheck)
                }
                Text(updater.explanation)
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .frame(width: 560, height: 520)
    }
}
