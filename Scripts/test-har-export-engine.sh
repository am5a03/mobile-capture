#!/bin/bash
# Synthetic checks inside the packaged engine; no listener, device or trust changes.
set -euo pipefail
root=$(cd "$(dirname "$0")/.." && pwd)
if [[ $# != 1 || ! -x "$1" ]]; then
    echo 'Usage: Scripts/test-har-export-engine.sh /absolute/path/to/packaged/mitmdump' >&2
    exit 64
fi
work=$(mktemp -d "${TMPDIR:-/tmp}/capture-har-engine.XXXXXX")
trap 'rm -rf "$work"' EXIT
cat > "$work/verify.py" <<'PY'
import importlib.util
import os
import sys
import unittest

class VerifyHAR:
    def load(self, loader):
        spec = importlib.util.spec_from_file_location("har_export_engine_tests", os.environ["CAPTURE_HAR_TEST_SOURCE"])
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(0 if result.wasSuccessful() else 1)

addons = [VerifyHAR()]
PY
CAPTURE_HAR_TEST_SOURCE="$root/Tests/Capture/test_har_export.py" \
    "$1" --no-server --set "confdir=$work/config" -s "$work/verify.py"
