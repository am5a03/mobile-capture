import json
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile


KEYS = {
    "schemaVersion", "command", "scope", "platform", "captureNetwork", "captureLogs",
    "appPath", "checkedAt", "macPrerequisitesReady", "checks", "repairs", "deviceSetup", "error",
}


def invoke(command, expected, *, cwd=None, env=None, network=True, logs=False, app=None):
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, timeout=120)
    assert result.returncode == expected, (command, result.returncode, result.stdout, result.stderr)
    assert result.stderr == "", result.stderr
    assert result.stdout.endswith("\n") and len(result.stdout.splitlines()) == 1, result.stdout
    value = json.loads(result.stdout)
    assert set(value) == KEYS, value
    assert list(value) == sorted(value), value
    assert value["schemaVersion"] == 1 and value["command"] == "doctor", value
    assert value["scope"] == "macPrerequisites", value
    assert value["captureNetwork"] is network and value["captureLogs"] is logs, value
    assert value["deviceSetup"]["status"] == "notChecked", value
    assert isinstance(value["deviceSetup"]["manualActions"], list), value
    assert value["repairs"] == sorted(set(value["repairs"])), value
    if expected in (0, 10):
        assert Path(value["appPath"]).samefile(app), value
        assert value["macPrerequisitesReady"] is (expected == 0), value
        assert value["error"] is None and value["checkedAt"].endswith("Z"), value
        assert value["checks"] and value["deviceSetup"]["manualActions"], value
        if expected == 0:
            assert all(row["status"] == "ready" for row in value["checks"]), value
        assert any(row["id"] == "mitmdump" for row in value["checks"]) is network, value
    else:
        assert value["appPath"] is None and value["checkedAt"] is None, value
        assert value["macPrerequisitesReady"] is None and value["checks"] == [], value
        assert value["error"]["code"] == ("invalidArguments" if expected == 64 else "owningApplication"), value
    return value


def smoke(app, ready):
    host = app / "Contents/MacOS/mobile-capture-host"
    expected = 0 if ready else 10
    with tempfile.TemporaryDirectory(prefix="agent-doctor-smoke-") as directory:
        work = Path(directory).resolve()
        output = work / "sessions"
        output.mkdir(mode=0o700)
        arguments = ["doctor", "--json", "--platform", "android", "--output-directory", str(output)]
        invoke([str(host), *arguments, "--sources", "network,logs"], expected, app=app, logs=True)
        invoke([str(host), *arguments, "--sources", "logs"], expected, app=app, network=False, logs=True)
        invoke([str(host), *arguments], expected, app=app)
        relative = os.path.relpath(host, work)
        invoke(["./" + relative, *arguments], expected, cwd=work, app=app)
        link = work / "host-link"
        link.symlink_to(host)
        invoke([str(link), *arguments], expected, app=app)
        environment = dict(os.environ, PATH=str(host.parent) + ":/usr/bin:/bin:/usr/sbin:/sbin")
        invoke(["mobile-capture-host", *arguments], expected, cwd=work, env=environment, app=app)
        for suffix in [[], ["--json"], ["--json", "--platform", "watch"],
                       ["--json", "--platform", "android", "--json"],
                       ["--json", "--platform", "android", "--output-directory", "relative"],
                       ["--json", "--platform", "android", "--app", str(app)],
                       ["--json", "--platform", "android", "--sources", "logs,network"]]:
            invoke([str(host), "doctor", *suffix], 64)
        detached = work / "mobile-capture-host"
        shutil.copy(host, detached)
        invoke([str(detached), *arguments], 70)
        invoke(["/bin/bash", "-c", 'exec -a "$1" "$2" "${@:3}"', "fixture", str(host), str(detached), *arguments], 70)
        assert list(output.iterdir()) == [], "Doctor wrote to the output directory"
    print("Agent Doctor CLI smoke passed. No devices were contacted.")


def fixture(host):
    with tempfile.TemporaryDirectory(prefix="agent-doctor-app-") as directory:
        app = Path(directory) / "Mobile Capture.app"
        executables = app / "Contents/MacOS"
        executables.mkdir(parents=True, mode=0o700)
        shutil.copy(host, executables / "mobile-capture-host")
        shutil.copy(host, executables / "Mobile Capture")
        with (app / "Contents/Info.plist").open("wb") as destination:
            plistlib.dump({"CFBundlePackageType": "APPL", "CFBundleIdentifier": "local.mobilecapture.fixture",
                          "CFBundleExecutable": "Mobile Capture", "MobileCaptureCompanion": True,
                          "MobileCaptureHandoffVersions": [1]}, destination)
        smoke(app, False)


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fixture-host":
        fixture(Path(sys.argv[2]).resolve())
    elif len(sys.argv) == 2:
        smoke(Path(sys.argv[1]).resolve(), True)
    else:
        raise SystemExit("Usage: agent_doctor_smoke.py APP | --fixture-host HOST")
