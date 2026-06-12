from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QObject, QCoreApplication, Signal

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.bridge.task_store import TaskStore
from app.memory_snapshot import current_process_memory


class PerformanceStub(QObject):
    lowMemoryModeChanged = Signal(bool)

    def __init__(self, low_memory: bool = False) -> None:
        super().__init__()
        self._low_memory = low_memory

    @property
    def lowMemoryMode(self) -> bool:
        return self._low_memory

    def set_low_memory(self, enabled: bool) -> None:
        if self._low_memory == enabled:
            return
        self._low_memory = enabled
        self.lowMemoryModeChanged.emit(enabled)


def sample(label: str) -> None:
    data = current_process_memory()
    print(
        f"{label}_mb="
        f"rss:{data.get('rss', 0.0):.1f},"
        f"private:{data.get('private', 0.0):.1f},"
        f"ws_private:{data.get('ws_private', 0.0):.1f}",
        flush=True,
    )


def make_url(index: int, size: int) -> str:
    base = f"https://example.com/watch/{index}?token="
    filler = ("abcdefghijklmnopqrstuvwxyz0123456789" * ((size // 36) + 2))[: max(0, size - len(base))]
    return base + filler


def seed(db_path: Path, count: int, url_size: int) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("INSERT INTO task_groups(name, sort_order) VALUES (?, ?)", ("long-url", 0))
        group_id = int(conn.execute("SELECT id FROM task_groups WHERE name = ?", ("long-url",)).fetchone()[0])
        rows = []
        for index in range(count):
            url = make_url(index + 1, url_size)
            rows.append(
                (
                    group_id,
                    "download",
                    f"长链接任务 {index + 1}",
                    url,
                    index % 101,
                    "普通",
                    f"{index % 59}m",
                    json.dumps({"source": url}, ensure_ascii=False, separators=(",", ":")),
                )
            )
        conn.executemany(
            """
            INSERT INTO tasks(group_id, task_type, name, status, progress, priority, duration, params_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )


def touch_rows(store: TaskStore, step: int) -> None:
    total = store.taskModel.rowCount()
    for row in range(0, total, step):
        store.prefetchAround(row)
        _ = store.taskModel.data(store.taskModel.index(row, 0))
        _ = store.taskModel.data(store.taskModel.index(row, 2))
        _ = store.taskModel.data(store.taskModel.index(row, 6))


def main() -> int:
    app = QCoreApplication([])
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 10000
    url_size = int(sys.argv[2]) if len(sys.argv) > 2 else 1200
    with tempfile.TemporaryDirectory(prefix="task-long-text-probe-", ignore_cleanup_errors=True) as tmp:
        db_path = Path(tmp) / "tasks.db"
        perf = PerformanceStub(low_memory=False)
        store = TaskStore(perf, db_path=db_path)
        with sqlite3.connect(db_path) as conn:
            conn.execute("DELETE FROM tasks")
            conn.execute("DELETE FROM task_groups")
        seed(db_path, count, url_size)
        store.refresh()
        target_index = 0
        for row in range(store.groupModel.rowCount()):
            if store.groupModel.data(store.groupModel.index(row, 0)) == "long-url":
                target_index = row
                break
        store.selectGroup(target_index)
        print(f"rows={store.taskModel.rowCount()} url_size={url_size}", flush=True)
        sample("ready")
        touch_rows(store, 113)
        sample("normal_cache_after_scroll")
        perf.set_low_memory(True)
        store.clearCaches()
        store.selectGroup(0)
        touch_rows(store, 113)
        sample("low_memory_after_scroll")
        store.shutdown()
        del store
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
