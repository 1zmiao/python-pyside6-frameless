from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.bridge.task_store import DEFAULT_GROUPS, DEFAULT_TASKS
from app.bridge.util import app_data_dir


def reset(db_path: Path | None = None) -> None:
    path = db_path or (app_data_dir() / "data" / "tasks.db")
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("DELETE FROM tasks")
        conn.execute("DELETE FROM task_groups")

        group_ids: dict[str, int] = {}
        for order, name in enumerate(DEFAULT_GROUPS):
            cursor = conn.execute("INSERT INTO task_groups(name, sort_order) VALUES (?, ?)", (name, order))
            group_ids[name] = int(cursor.lastrowid)

        conn.executemany(
            """
            INSERT INTO tasks(group_id, task_type, name, status, progress, priority, duration, params_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    group_ids[group_name],
                    task_type,
                    name,
                    status,
                    progress,
                    priority,
                    duration,
                    json.dumps(params, ensure_ascii=False, separators=(",", ":")),
                )
                for group_name, task_type, name, status, progress, priority, duration, params in DEFAULT_TASKS
            ],
        )


def main() -> int:
    reset()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
