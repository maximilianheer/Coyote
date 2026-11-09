"""Durable sequential CPU-only execution with independent ntfy delivery."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from common import REPO, save


def notify(root, name, message):
    path = root / "notifications" / (name + ".json")
    if not path.exists():
        save(path, dict(message=message, delivered=False))
    for pending in (root / "notifications").glob("*.json"):
        item = json.loads(pending.read_text())
        if item["delivered"]:
            continue
        response = subprocess.run(
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
            delivered=response.returncode == 0,
            response=response.stdout[:2000],
            attempted_at=time.time(),
        )
        save(pending, item)


def run(root):
    state = dict(pid=os.getpid(), status="running", started_at=time.time())
    env = dict(os.environ)
    env.update(
        CUDA_VISIBLE_DEVICES="-1",
        HIP_VISIBLE_DEVICES="-1",
        ROCR_VISIBLE_DEVICES="-1",
        TF_USE_LEGACY_KERAS="1",
        TF_CPP_MIN_LOG_LEVEL="3",
        OMP_NUM_THREADS="1",
        OPENBLAS_NUM_THREADS="1",
        MKL_NUM_THREADS="1",
        NUMEXPR_NUM_THREADS="1",
        TF_NUM_INTRAOP_THREADS="1",
        TF_NUM_INTEROP_THREADS="1",
        MPLCONFIGDIR=str(root / "preflight/mpl"),
    )
    stages = [
        ("int8_conversion", "int8_export.py", [str(root)]),
        ("fp32_lut_admission", "pilot.py", [str(root), "FP32"]),
    ]
    for session, models in [
        ("A", ["FP32", "QKERAS_W8A8"]),
        ("B", ["QKERAS_W8A8", "FP32"]),
    ]:
        for kind in models:
            stages.append(
                (f"{session}_{kind}", "benchmark.py", [str(root), kind, session])
            )
    try:
        for label, script, args in stages:
            record = root / "software" / (label + ".exit.json")
            if record.exists():
                assert json.loads(record.read_text())["returncode"] == 0
                continue
            state.update(stage=label, stage_started_at=time.time())
            argv = [
                "numactl",
                "--physcpubind=2",
                "--membind=2",
                str(REPO / "ml_baseline/.venv/bin/python"),
                str(Path(__file__).with_name(script)),
                *args,
            ]
            with (root / "software" / (label + ".log")).open("w") as log:
                process = subprocess.Popen(
                    argv, env=env, stdout=log, stderr=subprocess.STDOUT
                )
                state["child_pid"] = process.pid
                while process.poll() is None:
                    state["heartbeat"] = time.time()
                    save(root / "status.json", state)
                    time.sleep(2)
            save(
                record,
                dict(
                    returncode=process.returncode, finished_at=time.time(), command=argv
                ),
            )
            if process.returncode:
                if label == "int8_conversion":
                    save(
                        root / "int8_conversion/unavailable.json",
                        dict(
                            status="unavailable",
                            reason="See retained conversion log; primary faithful QKeras benchmark proceeds",
                            returncode=process.returncode,
                        ),
                    )
                    continue
                raise RuntimeError(
                    f"{label} failed with exit {process.returncode}; preserve and diagnose"
                )
            notify(
                root, label, f"CPU single-core benchmark stage passed: {label}. {root}"
            )
        state.update(status="measurements_complete", completed_at=time.time())
        save(root / "status.json", state)
        notify(
            root,
            "measurements_complete",
            f"CPU FP32/QKeras measurements complete; report and review next. {root}",
        )
    except BaseException as error:
        state.update(status="failed", error=repr(error), failed_at=time.time())
        save(root / "status.json", state)
        notify(
            root,
            "failure_" + str(int(time.time())),
            f"CPU benchmark requires diagnosis: {state.get('stage')}: {error}. {root}",
        )
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    root = parser.parse_args().root.resolve()
    with (root / "controller.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        run(root)
