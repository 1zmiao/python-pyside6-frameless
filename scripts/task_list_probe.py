from __future__ import annotations

import csv
import json
import sqlite3
import tempfile
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QCoreApplication, Signal, QTimer

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


def write_csv(path: Path, count: int) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["name", "status", "progress", "priority", "duration", "updated_at"])
        writer.writeheader()
        for i in range(count):
            writer.writerow(
                {
                    "name": f"CSV 任务 {i + 1}",
                    "status": "运行中" if i % 3 == 0 else "待处理",
                    "progress": i % 101,
                    "priority": ["低", "普通", "高"][i % 3],
                    "duration": f"{i % 47}m",
                    "updated_at": "2026-06-12 02:00:00",
                }
            )


def write_json(path: Path, count: int) -> None:
    rows = [
        {
            "任务": f"JSON 任务 {i + 1}",
            "状态": "完成" if i % 4 == 0 else "待处理",
            "进度": (i * 7) % 101,
            "优先级": ["低", "普通", "高", "紧急"][i % 4],
            "耗时": f"{i % 31}m",
        }
        for i in range(count)
    ]
    path.write_text(json.dumps({"group": "JSON 导入组", "tasks": rows}, ensure_ascii=False), encoding="utf-8")


def delete_first_rows(db_path: Path, group_id: int, count: int) -> None:
    with sqlite3.connect(db_path) as conn:
        ids = [
            int(row[0])
            for row in conn.execute(
                "SELECT id FROM tasks WHERE group_id = ? ORDER BY id LIMIT ?",
                (int(group_id), int(count)),
            ).fetchall()
        ]
        if ids:
            conn.executemany("DELETE FROM tasks WHERE id = ?", [(task_id,) for task_id in ids])


def finish_when_idle(app: QCoreApplication, store: TaskStore, callback) -> None:
    def check() -> None:
        if store.busy:
            QTimer.singleShot(50, check)
            return
        callback()

    check()


def main() -> int:
    app = QCoreApplication([])
    with tempfile.TemporaryDirectory(prefix="task-list-probe-") as tmp:
        root = Path(tmp)
        perf = PerformanceStub(low_memory=False)
        store = TaskStore(perf, db_path=root / "tasks.db")
        csv_path = root / "tasks.csv"
        json_path = root / "tasks.json"
        write_csv(csv_path, 6000)
        write_json(json_path, 6000)

        sample("ready")

        def after_csv() -> None:
            print(f"after_csv_groups={store.groupModel.rowCount()} rows={store.taskModel.rowCount()}", flush=True)
            sample("after_csv")
            store.importFile(str(json_path))
            finish_when_idle(app, store, after_json)

        def after_json() -> None:
            print(f"after_json_groups={store.groupModel.rowCount()} rows={store.taskModel.rowCount()}", flush=True)
            sample("after_json")
            store.selectGroup(1)
            for row in range(0, min(6000, store.taskModel.rowCount()), 137):
                store.prefetchAround(row)
                _ = store.taskModel.data(store.taskModel.index(row, 0))
                _ = store.taskModel.data(store.taskModel.index(row, 2))
            sample("after_scroll_like_access")
            delete_first_rows(root / "tasks.db", store.groupModel.group_id_at(store.currentGroupIndex), 500)
            store.refresh()
            print(f"after_delete_rows={store.taskModel.rowCount()}", flush=True)
            sample("after_delete")
            perf.set_low_memory(True)
            store.clearCaches()
            store.selectGroup(1)
            for row in range(0, min(6000, store.taskModel.rowCount()), 211):
                store.prefetchAround(row)
                _ = store.taskModel.data(store.taskModel.index(row, 0))
            sample("low_memory_access")
            store.shutdown()
            app.quit()

        store.importFile(str(csv_path))
        finish_when_idle(app, store, after_csv)
        app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
