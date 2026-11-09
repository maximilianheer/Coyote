#!/usr/bin/env python3
"""Bounded, event-aware main-thread wait for owned build transitions."""
import argparse
import fcntl
import json
from pathlib import Path
import time


def snapshot(root):
    state = json.loads((root / "builds/monitor_state.json").read_text())
    result = dict(status=state["status"], jobs={})
    for name, job in state["jobs"].items():
        item = dict(phase=job["phase"], repairs=job["repairs"], error=job.get("error"))
        if job["attempts"]:
            work = Path(job["attempts"][-1]["path"]) / "work/status.json"
            if work.exists():
                item["stage"] = json.loads(work.read_text()).get("stage")
        result["jobs"][name] = item
    return result


def wait(root, seconds):
    before = snapshot(root)
    start = time.monotonic()
    while time.monotonic() - start < seconds:
        state = snapshot(root)
        heartbeat_age = (
            time.time() - (root / "builds/monitor_state.json").stat().st_mtime
        )
        if heartbeat_age > 300:
            print(
                json.dumps(
                    dict(
                        event="controller_heartbeat_stale",
                        seconds=heartbeat_age,
                        state=state,
                    )
                ),
                flush=True,
            )
            return
        if state != before:
            print(json.dumps(dict(event="build_transition", state=state)), flush=True)
            return
        if state["status"] in ["complete", "monitor_error"]:
            print(
                json.dumps(dict(event="terminal_or_monitor_error", state=state)),
                flush=True,
            )
            return
        with (root / "builds/monitor.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                pass
            else:
                print(
                    json.dumps(dict(event="controller_not_holding_lock", state=state)),
                    flush=True,
                )
                return
        time.sleep(1)
    print(
        json.dumps(
            dict(
                event="bounded_wait_complete",
                waited_seconds=round(time.monotonic() - start),
                state=before,
            )
        ),
        flush=True,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--seconds", type=int, default=50)
    args = parser.parse_args()
    assert 1 <= args.seconds <= 55
    wait(args.root.resolve(), args.seconds)
