# Publish a downloadable release

Use this guide after the release workflow is merged into the default branch.
It builds the complete Apple Silicon app when you publish a GitHub Release, then
attaches the app ZIP and `SHA256SUMS` to that release. Tag pushes alone do not
publish downloads. Builds currently require macOS 26.

## Publish a development prerelease

1. Open [Releases](https://github.com/am5a03/mobile-capture/releases).
2. Choose **Draft a new release**.
3. Create a tag such as `v0.1.1-beta.1` from the tested commit.
4. Select **Set as a pre-release** and add the release notes.
5. Choose **Publish release**.
6. Wait for **Downloadable release** in Actions to finish.

The release's Assets section then contains
`MobileCapture-macOS-arm64-development.zip` and `SHA256SUMS`. The ZIP includes
mitmproxy, its Python interpreter and Android tools. Physical iPhone USB tools
remain external in this ordinary package. Simulator capture requires Xcode.
The app's numeric version comes from the tag, so `v0.1.1-beta.1` builds app version
`0.1.1`. The release workflow run number supplies the app build number.

Development prereleases are ad-hoc signed and not notarized. State that limitation
in the release notes. They are for testers who trust this project. macOS can block
them. [Apple explains how downloaded apps are checked](https://support.apple.com/en-us/102445).
A development prerelease is available without Apple signing credentials.

## Configure stable release signing

Add the following under **Settings > Secrets and variables > Actions** in this
repository. Store private certificate and key material in GitHub Secrets.

Repository secrets:

- `APPLE_CERTIFICATE_P12_BASE64`: Base64 of a Developer ID Application certificate
  exported with its private key as a `.p12` file.
- `APPLE_CERTIFICATE_PASSWORD`: Password for that `.p12` file.
- `APPLE_NOTARY_KEY_P8_BASE64`: Base64 of the App Store Connect API `.p8` key used
  for notarization.

Repository variables:

- `APPLE_TEAM_ID`: Your Apple Developer team ID.
- `CAPTURE_BUNDLE_IDENTIFIER`: Your owner-controlled reverse-DNS release identity.
  The provisional `local.mobilecapture.development` identity is rejected.
- `APPLE_NOTARY_KEY_ID`: ID of the notarization API key.
- `APPLE_NOTARY_ISSUER_ID`: Issuer UUID for that API key.

Keep the original certificate and API key files outside Git. Do not paste their
contents into issues, release notes or workflow files. Follow
[GitHub's certificate setup guidance](https://docs.github.com/en/actions/how-tos/deploy/deploy-to-third-party-platforms/sign-xcode-applications)
when exporting the certificate and saving secrets.

The workflow imports credentials into a temporary keychain on a GitHub-hosted
runner. It removes the keychain and decoded files when the job ends. The signing
setup refuses to run on a developer Mac or a self-hosted runner.

## Publish a stable release

1. Complete the outstanding device, fresh-Mac and release acceptance checks in
   [the distribution guide](CAPTURE-DISTRIBUTION.md).
2. Configure the signing secrets and variables above.
3. Publish a release with a tag such as `v0.1.1` and leave **Set as a pre-release** off.
4. Wait for **Downloadable release** to finish.

The workflow signs the app and nested tools with Developer ID, submits the ZIP
for notarization, staples the accepted ticket and checks Gatekeeper acceptance.
A missing credential, failed test, hash mismatch, signing error or notarization
failure stops the upload. Stable releases never fall back to development signing.

Successful stable releases contain `MobileCapture-macOS-arm64.zip` and
`SHA256SUMS`. The latest stable app then has this download URL:

<https://github.com/am5a03/mobile-capture/releases/latest/download/MobileCapture-macOS-arm64.zip>

The URL becomes usable after the first successful stable release. Draft releases
and releases whose build failed do not have a finished app download. Publishing
makes the release page visible before the build has finished. Wait for the assets.

To retry a failed build, use **Re-run jobs** in Actions. Uploads are serialized per
tag. A successful retry replaces this workflow's matching asset names through
`gh release upload --clobber`. Publish a new version for a changed source commit.

## Install the app

1. Open the [Releases page](https://github.com/am5a03/mobile-capture/releases).
2. Download the app ZIP listed above for your chosen release.
3. Unzip it and move **Mobile Capture.app** into **Applications**.
4. Open the app and follow **Device Setup** for the connected phone.

The app includes Python, mitmproxy and Android connection tools. Users do not
build source or run Homebrew for the bundled Android/network route. Phone-side
certificate installation, trust and VPN steps remain part of Device Setup.

## Verify the release machinery locally

Run the release behavior tests:

```sh
python3 -B -m unittest discover -s Tests/Release -p 'test_*.py' -v
```

Prepare a clean cache from the exact reviewed official archives:

```sh
python3 -B Scripts/prepare-capture-cache.py --cache-root /tmp/capture-release-cache
```

Both archives have pinned SHA256 values in
`Dependencies/Capture/downloads-arm64.lock.json`. The downloader binds that file
to the existing payload lock, verifies archives before extraction, then asks the
Swift dependency packager to verify every admitted payload file. A changed lock
or tampered cache fails the build. Normal pull-request CI repeats this path and
builds a complete development ZIP with an overridden app version.

Developer ID signing, Apple notarization and the final GitHub asset upload require
their real credentials and a published release. Local fixtures do not prove those
external operations. The release workflow does not bundle the experimental USB
candidate or change the existing hardware/release acceptance requirements.
