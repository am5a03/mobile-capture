#!/bin/bash
set -euo pipefail
if [[ $# -lt 1 || $# -gt 2 || "$1" != /* || ! -d "$1/Contents/MacOS" || ( $# -eq 2 && "$2" != --simulator ) ]]; then
  echo 'Usage: test-agent-doctor-bundle.sh "/absolute/path/Mobile Capture.app" [--simulator]' >&2
  exit 64
fi
repoRoot=$(cd "$(dirname "$0")/.." && pwd)
python3 -B "$repoRoot/Tests/Doctor/agent_doctor_smoke.py" "$@"
