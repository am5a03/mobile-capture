#!/bin/bash
# Fixture-only suites. No phone captures, dependency installations or trust changes.
set -euo pipefail
cd "$(dirname "$0")/.."
case "${1:-all}" in
  core)
    bash Scripts/test-capture-handoff.sh
    bash Scripts/test-capture-plan.sh
    bash Scripts/test-capture-setup-readiness.sh
    bash Scripts/test-capture-usb-discovery.sh
    bash Scripts/test-iphone-capture-setup.sh
    ;;
  services)
    bash Scripts/test-capture-doctor.sh
    bash Scripts/test-capture-setup-store.sh
    bash Scripts/test-native-capture-services.sh
    bash Scripts/test-native-capture-lifecycle.sh
    bash Scripts/test-capture-log-writer.sh
    ;;
  timeline)
    bash Scripts/test-native-timeline.sh
    bash Scripts/test-capture-timeline.sh
    bash Scripts/test-capture-timeline-list.sh
    bash Scripts/test-capture-command-target.sh
    ;;
  python)
    python3 -B -m unittest discover -s Tests/Capture -p 'test_*.py' -v
    ;;
  all)
    for group in core services timeline python; do bash Scripts/test-all.sh "$group"; done
    ;;
  *) echo "Usage: Scripts/test-all.sh [core|services|timeline|python|all]" >&2; exit 2 ;;
esac
