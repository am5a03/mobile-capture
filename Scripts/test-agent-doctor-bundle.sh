#!/bin/bash
set -euo pipefail
if [[ $# -ne 1 || "$1" != /* || ! -d "$1/Contents/MacOS" ]]; then
  echo 'Usage: test-agent-doctor-bundle.sh "/absolute/path/Mobile Capture.app"' >&2
  exit 64
fi
repoRoot=$(cd "$(dirname "$0")/.." && pwd)
python3 -B "$repoRoot/Tests/Doctor/agent_doctor_smoke.py" "$1"
