import Foundation

struct CaptureUpdateConfiguration {
    let feedURL: URL
    let channel: String
    let releaseTag: String

    init?(info: [String: Any], bundleIdentifier: String?) {
        guard info["CaptureDistributionUpdatesEnabled"] as? Bool == true,
              bundleIdentifier == "local.mobilecapture.development",
              info["CFBundleIdentifier"] as? String == bundleIdentifier,
              let channel = info["CaptureUpdateChannel"] as? String, channel == "beta",
              let tag = info["CaptureBetaReleaseTag"] as? String,
              tag.range(of: #"^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)-beta\.[1-9][0-9]*$"#, options: .regularExpression) != nil,
              let feed = info["SUFeedURL"] as? String, let url = URL(string: feed),
              url.scheme == "https", url.host?.isEmpty == false, url.user == nil, url.password == nil,
              url.fragment == nil, url.query == nil,
              let publicKey = info["SUPublicEDKey"] as? String, Data(base64Encoded: publicKey)?.count == 32,
              info["SUEnableAutomaticChecks"] as? Bool == false,
              info["SUAllowsAutomaticUpdates"] as? Bool == false,
              info["SUAutomaticallyUpdate"] as? Bool == false,
              info["SURequireSignedFeed"] as? Bool == true,
              info["SUVerifyUpdateBeforeExtraction"] as? Bool == true,
              info["SUSendProfileInfo"] as? Bool == false else { return nil }
        feedURL = url
        self.channel = channel
        releaseTag = tag
    }
}
