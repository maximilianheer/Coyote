#!/usr/bin/env python3
"""Durable hardware schedule; the main thread supervises and repairs failures."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import socket
import subprocess
import time

from readers_spec import CONFIGURATIONS, IMAGE_IDS

REPO = Path(__file__).resolve().parents[4]
PYTHON = REPO / "hls4ml/optimize/runs/gpu_fp32_20261018/venv/bin/python"
BASE = REPO / "hls4ml/optimize/runs/hbm_network_20261107"
PREVIOUS = REPO / "hls4ml/optimize/runs/hbm_benchmark_20261108"


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def notify(root, identifier, message):
    # Durable delivery retries are independent from completed hardware stages.
    directory = root / "notifications"
    directory.mkdir(exist_ok=True)
    path = directory / f"{identifier}.json"
    if not path.exists():
        save(path, dict(id=identifier, message=message, delivered=False, tries=0))
    for pending in directory.glob("*.json"):
        item = json.loads(pending.read_text())
        if item["delivered"]:
            continue
        result = subprocess.run(
            [
                "curl",
                "-fsS",
                "--max-time",
                "5",
                "--data-binary",
                item["message"],
                "https://ntfy.sh/coyote-build-sdeheredia",
            ],
            capture_output=True,
            text=True,
        )
        item.update(
            delivered=result.returncode == 0,
            tries=item["tries"] + 1,
            last_try=time.time(),
            response=result.stdout[:2000],
        )
        save(pending, item)


def images(root):
    accepted = json.loads((root / "builds/artifact_manifest.json").read_text())
    selected = {}
    for variant in [10, 11]:
        job = BASE / IMAGE_IDS[variant] / "attempt_01"
        manifest = json.loads((job / "artifacts.json").read_text())
        path = job / "build/bitstreams/cyt_top.bit"
        assert sha(path) == manifest["files"]["build/bitstreams/cyt_top.bit"]
        selected[variant] = dict(
            path=str(path), sha256=sha(path), role="fresh HBM-resident control"
        )
    for variant in [14, 15, 16]:
        if IMAGE_IDS[variant] in accepted:
            evidence = accepted[IMAGE_IDS[variant]]
            assert evidence["verification"]["status"] == "passed"
            item = evidence["files"]["build/bitstreams/cyt_top.bit"]
            assert sha(Path(item["path"])) == item["sha256"]
            selected[variant] = dict(item, role="accepted candidate")
    save(root / "hardware_selection.json", selected)
    return selected


def run(root):
    assert socket.gethostname() == "hacc-gpu-u55c-01.inf.ethz.ch"
    state = dict(
        pid=os.getpid(),
        status="waiting_board_lease",
        stage="preflight",
        started_at=time.time(),
    )
    selected = images(root)
    board = root / "hardware"
    board.mkdir(exist_ok=True)
    helper = board / "program_hacc_local.sh"
    if not helper.exists():
        text = (PREVIOUS / "software/program_hacc_local.sh").read_text()
        # Correct the site helper's device1 lookup only in this local copy.
        text = text.replace("get network -d 1", "get network -d $DEVICE")
        text = text.replace('awk \'$1 == "1:"', 'awk -v slot="$DEVICE:" \'$1 == slot')
        helper.write_text(text)
    driver = PREVIOUS / "software/driver/build/coyote_driver.ko"
    assert driver.exists()
    save(
        root / "driver_identity.json",
        dict(
            path=str(driver),
            sha256=sha(driver),
            kernel=os.uname().release,
            source=str(PREVIOUS / "software/driver"),
        ),
    )
    environment = dict(os.environ)
    environment["PATH"] = "/tools/Xilinx/Vivado/2024.2/bin:" + environment["PATH"]
    environment["PYTHONPATH"] = str(root / "runtime/build")
    for name in [
        "HIP_VISIBLE_DEVICES",
        "ROCR_VISIBLE_DEVICES",
        "CUDA_VISIBLE_DEVICES",
        "GPU_DEVICE_ORDINAL",
    ]:
        environment.pop(name, None)
    environment["LD_LIBRARY_PATH"] = (
        str(root / "runtime/build/coyote") + ":/opt/rocm/lib"
    )
    lock = REPO / "hls4ml/optimize/runs/gpu_fp32_20261018/board_device.lock"

    def update(**values):
        state.update(values, heartbeat=time.time())
        save(root / "hardware_status.json", state)

    def command(label, argv, cwd, result_directory=None):
        record = board / f"{label}.result.json"
        if record.exists():
            previous = json.loads(record.read_text())
            assert previous["exit_code"] == 0, previous
            return
        update(stage=label, status="running", stage_started_at=time.time())
        log_path = board / f"{label}.log"
        with log_path.open("w") as log:
            process = subprocess.Popen(
                argv, cwd=cwd, env=environment, stdout=log, stderr=subprocess.STDOUT
            )
            update(child_pid=process.pid, log=str(log_path))
            announced_failure = False
            while process.poll() is None:
                if result_directory and (result_directory / "status.json").exists():
                    child_state = json.loads(
                        (result_directory / "status.json").read_text()
                    )
                    if child_state["status"] == "failed_holding_mappings":
                        update(status="needs_safe_drain", failure=child_state)
                        if not announced_failure:
                            notify(
                                root,
                                label + "_safe_drain",
                                f"HBM reader benchmark {label} failed with live mappings retained; main-thread safe-drain diagnosis required. {result_directory}",
                            )
                            announced_failure = True
                if time.time() - state["stage_started_at"] > 86400:
                    update(
                        status="needs_attention",
                        error="24-hour stage watchdog; controlled diagnosis required",
                    )
                    notify(
                        root,
                        label + "_watchdog",
                        f"HBM benchmark stage watchdog: {label}; process retained pending safe diagnosis. {root}",
                    )
                update()
                time.sleep(2)
        result = dict(
            exit_code=process.returncode, completed_at=time.time(), command=argv
        )
        save(record, result)
        if process.returncode:
            update(status="failed", error=f"{label} exited {process.returncode}")
            notify(
                root,
                label + "_failed",
                f"HBM reader benchmark FAILED: {label}; main agent diagnosing. {log_path}",
            )
            raise RuntimeError(state["error"])

    with lock.open("a") as lease:
        while True:
            try:
                fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                update(status="waiting_board_lease")
                time.sleep(5)
        notify(
            root,
            "hardware_start",
            f"HBM reader hardware benchmark campaign acquired device2 lease: two rounds, {len(selected)} images. {root}",
        )
        try:
            for session, order in [
                ("A", [10, 14, 15, 16, 11]),
                ("B", [11, 16, 15, 14, 10]),
            ]:
                for variant in order:
                    if variant not in selected:
                        continue
                    item = selected[variant]
                    assert sha(Path(item["path"])) == item["sha256"]
                    label = f"{session}_{variant}_program"
                    program = shlex.join(
                        [
                            "env",
                            "-u",
                            "LD_LIBRARY_PATH",
                            "bash",
                            str(helper),
                            item["path"],
                            str(driver),
                            "2",
                        ]
                    )
                    command(
                        label,
                        [
                            "script",
                            "--quiet",
                            "--return",
                            "--command",
                            program,
                            "/dev/null",
                        ],
                        REPO.parent / "util",
                    )
                    text = (board / f"{label}.log").read_text()
                    assert (
                        "program_hw_devices: Time" in text
                        and "XFL13BA4HVZYA" in text
                        and "ERROR:" not in text
                    )
                    assert "Inserting coyote_driver.ko" in text
                    assert (
                        Path("/sys/bus/pci/devices/0000:81:00.0") / "vendor"
                    ).read_text().strip() == "0x10ee"
                    assert (
                        Path("/sys/bus/pci/devices/0000:03:00.0") / "device"
                    ).read_text().strip() == "0x740f"
                    identity = dict(
                        session=session,
                        variant=variant,
                        image=item,
                        driver_sha256=sha(driver),
                        device=2,
                        serial="XFL13BA4HVZYA",
                        bdf="0000:81:00.0",
                        gpu="0000:03:00.0",
                    )
                    save(board / f"{session}_{variant}_identity.json", identity)
                    configurations = [
                        config
                        for config in CONFIGURATIONS
                        if config["variant"] == variant
                    ]
                    if session == "B":
                        configurations.reverse()
                    for configuration in configurations:
                        for mode, warmup, repeats in [
                            ("admission", 0, 20),
                            ("pilot", 2, 10),
                            ("main", 20, 200),
                            ("diagnostic", 2, 20),
                        ]:
                            label = f"{session}_{configuration['key']}_{mode}"
                            destination = board / session / configuration["key"] / mode
                            argv = [
                                str(PYTHON),
                                str(Path(__file__).with_name("readers_benchmark.py")),
                                "--output",
                                str(destination),
                                "--configuration",
                                configuration["key"],
                                "--session",
                                session,
                                "--mode",
                                mode,
                                "--warmup",
                                str(warmup),
                                "--repeat",
                                str(repeats),
                            ]
                            if session == "B":
                                argv.append("--reverse")
                            if mode == "diagnostic":
                                argv += ["--manifest", str(root / "diagnostics.tsv")]
                            command(label, argv, REPO, destination)
                            status = json.loads(
                                (destination / "status.json").read_text()
                            )
                            assert status["status"] == "passed"
                            assert status["variant"] == variant
                            if mode == "admission":
                                assert status["calls"] == 520
                            if mode == "main":
                                assert status["calls"] == 2640
                            notify(
                                root,
                                label,
                                f"HBM benchmark passed: round {session}, {configuration['key']}, {mode}; {status['calls']} calls. {destination}",
                            )
            update(
                status="complete",
                stage="hardware_complete",
                completed_at=time.time(),
                omitted_variants=[
                    variant for variant in [14, 15, 16] if variant not in selected
                ],
            )
            notify(
                root,
                "hardware_complete",
                f"HBM reader measurements complete; proceeding to comparison PDF/review. {root}",
            )
        except BaseException as error:
            update(status="failed", error=repr(error))
            notify(
                root,
                f"hardware_exception_{int(time.time())}",
                f'HBM reader hardware campaign stopped for main-thread diagnosis: {state["stage"]}: {error}. {root}',
            )
            raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    root = parser.parse_args().root.resolve()
    with (root / "hardware_controller.lock").open("a") as singleton:
        fcntl.flock(singleton, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(root)
