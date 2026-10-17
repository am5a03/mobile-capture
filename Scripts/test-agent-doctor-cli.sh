#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")/.."
work=$(mktemp -d "${TMPDIR:-/tmp}/agent-doctor-cli.XXXXXX")
trap 'rm -rf "$work"' EXIT
CLANG_MODULE_CACHE_PATH="$work/module-cache" swiftc -swift-version 6 -warnings-as-errors -parse-as-library \
  Sources/Core/Support.swift Sources/Core/Shell/ShellRunner.swift Sources/Core/CaptureModels.swift \
  Sources/Core/Capture/*.swift Sources/Core/CaptureServices/*.swift Sources/Core/CaptureLifecycle/*.swift \
  Sources/CaptureHost/MobileCaptureHostMain.swift -o "$work/mobile-capture-host"
python3 -B Tests/Doctor/agent_doctor_smoke.py --fixture-host "$work/mobile-capture-host" "$@"
