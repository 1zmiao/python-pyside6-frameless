from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import psutil


ROOT = Path(__file__).resolve().parents[1]


def mb(value: int) -> float:
    return round(value / 1024 / 1024, 1)


def memory_sample(process: psutil.Process) -> dict[str, float]:
    info = process.memory_info()
    sample = {"rss": mb(info.rss)}
    try:
        full = process.memory_full_info()
        sample["uss"] = mb(getattr(full, "uss", 0))
        sample["private"] = mb(getattr(full, "private", 0))
    except Exception:
        sample["uss"] = 0.0
        sample["private"] = 0.0
    return sample


def main() -> int:
    env = os.environ.copy()
    env["QROUNDEDFRAME_SMOKE_CLOSE_MS"] = "10500"
    env["QROUNDEDFRAME_SMOKE_CHILD_PAGE"] = "about"
    env["QROUNDEDFRAME_SMOKE_CHILD_CLOSE_MS"] = "6500"
    env["QROUNDEDFRAME_SMOKE_CHILD_CLOSE_MODE"] = "window"
    proc = subprocess.Popen([sys.executable, "run.py"], cwd=ROOT, env=env)
    ps = psutil.Process(proc.pid)
    samples: list[tuple[str, float]] = []
    try:
        time.sleep(0.35)
        samples.append(("main_ready", memory_sample(ps)))
        time.sleep(1.35)
        samples.append(("child_open", memory_sample(ps)))
        time.sleep(2.4)
        samples.append(("child_open_late", memory_sample(ps)))
        time.sleep(2.9)
        samples.append(("child_closed", memory_sample(ps)))
        time.sleep(1.8)
        samples.append(("child_closed_late", memory_sample(ps)))
        proc.wait(timeout=8)
    except Exception:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        raise
    print(f"exit_code={proc.returncode}")
    for name, value in samples:
        print(f"{name}_mb={value}")
    if len(samples) >= 2:
        base = samples[0][1]
        opened = samples[1][1]
        delta = {key: round(opened.get(key, 0.0) - base.get(key, 0.0), 1) for key in base}
        print(f"child_open_delta_mb={delta}")
    if len(samples) >= 3:
        base = samples[0][1]
        opened_late = samples[2][1]
        delta = {key: round(opened_late.get(key, 0.0) - base.get(key, 0.0), 1) for key in base}
        print(f"child_open_late_delta_mb={delta}")
    if len(samples) >= 5:
        base = samples[0][1]
        closed_late = samples[4][1]
        delta = {key: round(closed_late.get(key, 0.0) - base.get(key, 0.0), 1) for key in base}
        print(f"child_closed_late_delta_mb={delta}")
    return 0 if proc.returncode in (0, None) else int(proc.returncode)


if __name__ == "__main__":
    raise SystemExit(main())
