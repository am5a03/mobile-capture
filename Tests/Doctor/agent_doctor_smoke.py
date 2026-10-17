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
    accepted = expected if isinstance(expected, tuple) else (expected,)
    assert result.returncode in accepted, (command, result.returncode, result.stdout, result.stderr)
    actual = result.returncode
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
    if actual in (0, 10):
        assert Path(value["appPath"]).samefile(app), value
        assert value["macPrerequisitesReady"] is (actual == 0), value
        assert value["error"] is None and value["checkedAt"].endswith("Z"), value
        assert value["checks"] and value["deviceSetup"]["manualActions"], value
        if actual == 0:
            assert all(row["status"] == "ready" for row in value["checks"]), value
        assert any(row["id"] == "mitmdump" for row in value["checks"]) is network, value
    else:
        assert value["appPath"] is None and value["checkedAt"] is None, value
        assert value["macPrerequisitesReady"] is None and value["checks"] == [], value
        assert value["error"]["code"] == ("invalidArguments" if actual == 64 else "owningApplication"), value
    return value


def smoke(app, ready, simulator=False):
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
        if simulator:
            selection = subprocess.run(["/usr/bin/xcode-select", "--print-path"], capture_output=True, text=True,
                                       timeout=10, check=True, env={"PATH": "/usr/bin:/bin", "LC_ALL": "C"})
            developer = Path(selection.stdout.strip())
            if developer.suffix == ".app":
                developer = developer / "Contents/Developer"
            selected_simulator = developer / "usr/bin/simctl"
            simulator_arguments = ["doctor", "--json", "--platform", "simulator", "--output-directory", str(output)]
            for sources in ("network,logs", "logs"):
                value = invoke([str(host), *simulator_arguments, "--sources", sources], (0, 10), app=app, network=sources != "logs", logs=True)
                checks = [row for row in value["checks"] if row["id"] == "simctl"]
                assert len(checks) == 1 and checks[0]["source"] == "system", value
                assert checks[0]["status"] in ("ready", "incompatible"), value
                assert Path(checks[0]["path"]).is_absolute() and Path(checks[0]["path"]).samefile(selected_simulator), value
                print(f"Simulator Doctor {sources} reports {checks[0]['status']} for {checks[0]['path']}.")
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


def fixture(host, simulator=False):
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
        smoke(app, False, simulator=simulator)


if __name__ == "__main__":
    if len(sys.argv) in (3, 4) and sys.argv[1] == "--fixture-host" and (len(sys.argv) == 3 or sys.argv[3] == "--simulator"):
        fixture(Path(sys.argv[2]).resolve(), simulator=len(sys.argv) == 4)
    elif len(sys.argv) in (2, 3) and (len(sys.argv) == 2 or sys.argv[2] == "--simulator"):
        smoke(Path(sys.argv[1]).resolve(), True, simulator=len(sys.argv) == 3)
    else:
        raise SystemExit("Usage: agent_doctor_smoke.py APP [--simulator] | --fixture-host HOST [--simulator]")
