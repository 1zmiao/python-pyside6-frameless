from __future__ import annotations

import csv
import json
import sqlite3
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PySide6.QtCore import QAbstractListModel, QAbstractTableModel, QModelIndex, QObject, Property, Qt, Signal, Slot

from app.runtime_logging import write_runtime_log

from .util import app_data_dir, to_python


TASK_COLUMNS = ("name", "task_type", "status", "progress", "priority", "duration", "updated_at")
TASK_HEADERS = ("名称", "类型", "链接", "进度", "优先级", "耗时", "更新时间")
DEFAULT_GROUPS = ("work", "bilibili", "upup", "link", "top")
SAMPLE_LONG_URL = (
    "https://example.com/parser/source?"
    "id=demo-item&token=abcdefghijklmnopqrstuvwxyz0123456789"
    "abcdefghijklmnopqrstuvwxyz0123456789abcdefghijklmnopqrstuvwxyz0123456789"
)
DEFAULT_TASKS = (
    ("work", "default", "链接解析工作项", SAMPLE_LONG_URL, 0, "普通", "-", {"target": SAMPLE_LONG_URL, "note": "默认长链接解析样例"}),
    ("bilibili", "download", "视频链接解析样例", SAMPLE_LONG_URL + "&platform=bilibili", 0, "普通", "-", {"source": SAMPLE_LONG_URL + "&platform=bilibili", "directory": "", "retry": "3"}),
    ("upup", "script", "脚本解析任务样例", SAMPLE_LONG_URL + "&handler=script", 0, "普通", "-", {"script": "python parse_link.py", "arguments": SAMPLE_LONG_URL, "cwd": ""}),
    ("link", "default", "通用链接任务样例", SAMPLE_LONG_URL + "&group=link", 0, "普通", "-", {"target": SAMPLE_LONG_URL + "&group=link", "note": ""}),
    ("top", "default", "置顶链接任务样例", SAMPLE_LONG_URL + "&pinned=true", 0, "普通", "-", {"target": SAMPLE_LONG_URL + "&pinned=true", "note": ""}),
)


@dataclass(frozen=True)
class CacheProfile:
    page_size: int
    max_pages: int


NORMAL_CACHE = CacheProfile(page_size=256, max_pages=6)
LOW_MEMORY_CACHE = CacheProfile(page_size=96, max_pages=2)


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), timeout=20.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _init_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with _connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id INTEGER NOT NULL REFERENCES task_groups(id) ON DELETE CASCADE,
                task_type TEXT NOT NULL DEFAULT 'default',
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '待处理',
                progress INTEGER NOT NULL DEFAULT 0,
                priority TEXT NOT NULL DEFAULT '普通',
                duration TEXT NOT NULL DEFAULT '-',
                params_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        columns = {str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)").fetchall()}
        if "task_type" not in columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN task_type TEXT NOT NULL DEFAULT 'default'")
        if "params_json" not in columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN params_json TEXT NOT NULL DEFAULT '{}'")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_group_id_id ON tasks(group_id, id)")
        # 旧版本会自动创建“默认分组”。现在任务列表允许 0 分组，只清掉空的历史默认分组，避免误删用户已有任务。
        conn.execute(
            """
            DELETE FROM task_groups
            WHERE name = '默认分组'
              AND NOT EXISTS (
                  SELECT 1 FROM tasks WHERE tasks.group_id = task_groups.id
              )
            """
        )
        _seed_default_data_if_empty(conn)


def _seed_default_data_if_empty(conn: sqlite3.Connection) -> None:
    group_count = int(conn.execute("SELECT COUNT(*) FROM task_groups").fetchone()[0])
    task_count = int(conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0])
    if group_count > 0 or task_count > 0:
        return
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


def _normalize_path(path: str) -> Path:
    text = str(path or "").strip()
    if text.startswith("file:///"):
        text = text[8:]
    return Path(text)


def _first_value(row: dict[str, Any], names: tuple[str, ...], fallback: Any = "") -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for name in names:
        key = name.lower()
        if key in lowered and lowered[key] not in (None, ""):
            return lowered[key]
    return fallback


def _safe_int(value: Any, fallback: int = 0) -> int:
    try:
        return max(0, min(100, int(float(value))))
    except Exception:
        return fallback


def _bounded_int(value: Any, fallback: int, minimum: int, maximum: int) -> int:
    try:
        return max(minimum, min(maximum, int(float(value))))
    except Exception:
        return fallback


def _task_from_mapping(row: dict[str, Any], fallback_name: str) -> dict[str, Any]:
    task_type = str(_first_value(row, ("type", "task_type", "category", "类型", "分类"), "default")).strip() or "default"
    name = str(_first_value(row, ("name", "title", "task", "任务", "名称", "标题"), fallback_name)).strip() or fallback_name
    status = str(_first_value(row, ("status", "state", "状态"), "待处理")).strip() or "待处理"
    priority = str(_first_value(row, ("priority", "level", "优先级"), "普通")).strip() or "普通"
    duration = str(_first_value(row, ("duration", "elapsed", "耗时"), "-")).strip() or "-"
    updated_at = str(_first_value(row, ("updated_at", "updated", "mtime", "更新时间", "修改时间"), "")).strip()
    progress = _safe_int(_first_value(row, ("progress", "percent", "进度"), 0), 0)
    return {
        "name": name,
        "task_type": task_type,
        "status": status,
        "progress": progress,
        "priority": priority,
        "duration": duration,
        "updated_at": updated_at,
    }


def _task_type_from_text(text: str) -> str:
    lowered = str(text or "").strip().lower()
    if lowered.startswith(("url:", "http://", "https://", "download:", "import:")):
        return "download"
    if lowered.startswith(("script:", "cmd:", "powershell:", "python:", "bash:")):
        return "script"
    return "default"


def _loads_params(value: Any) -> dict[str, Any]:
    try:
        data = json.loads(str(value or "{}"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _load_import_rows(path: Path) -> tuple[str, list[dict[str, Any]]]:
    suffix = path.suffix.lower()
    group_name = path.stem or "导入任务"
    rows: list[dict[str, Any]] = []
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            group_name = str(payload.get("group") or payload.get("name") or group_name)
            data = payload.get("tasks") or payload.get("items") or payload.get("rows") or []
        else:
            data = payload
        if not isinstance(data, list):
            raise ValueError("JSON 必须是列表，或包含 tasks/items/rows 的对象。")
        for index, item in enumerate(data, 1):
            if isinstance(item, dict):
                rows.append(_task_from_mapping(item, f"任务 {index}"))
            else:
                rows.append(_task_from_mapping({"name": item}, f"任务 {index}"))
        return group_name, rows

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        sample = handle.read(4096)
        handle.seek(0)
        dialect = csv.Sniffer().sniff(sample) if sample.strip() else csv.excel
        reader = csv.DictReader(handle, dialect=dialect)
        for index, row in enumerate(reader, 1):
            rows.append(_task_from_mapping(dict(row), f"任务 {index}"))
    return group_name, rows


class TaskGroupModel(QAbstractListModel):
    IdRole = Qt.UserRole + 1
    NameRole = Qt.UserRole + 2
    CountRole = Qt.UserRole + 3

    def __init__(self, db_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._rows: list[dict[str, Any]] = []
        self.reload()

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        return {
            int(self.IdRole): b"groupId",
            int(self.NameRole): b"name",
            int(self.CountRole): b"count",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < len(self._rows):
            return None
        row = self._rows[index.row()]
        if role in (Qt.DisplayRole, self.NameRole):
            return row["name"]
        if role == self.IdRole:
            return row["id"]
        if role == self.CountRole:
            return row["count"]
        return None

    def group_id_at(self, row: int) -> int:
        if 0 <= row < len(self._rows):
            return int(self._rows[row]["id"])
        return 0

    def group_ids_at(self, rows: list[int]) -> list[int]:
        ids: list[int] = []
        for row in rows:
            group_id = self.group_id_at(int(row))
            if group_id > 0:
                ids.append(group_id)
        return ids

    def row_for_group_id(self, group_id: int) -> int:
        wanted = int(group_id or 0)
        for index, row in enumerate(self._rows):
            if int(row["id"]) == wanted:
                return index
        return -1

    def reload(self) -> None:
        with _connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT g.id, g.name, COUNT(t.id) AS count
                FROM task_groups g
                LEFT JOIN tasks t ON t.group_id = g.id
                GROUP BY g.id, g.name, g.sort_order
                ORDER BY g.sort_order, g.id
                """
            ).fetchall()
        self.beginResetModel()
        self._rows = [{"id": int(row[0]), "name": str(row[1]), "count": int(row[2])} for row in rows]
        self.endResetModel()


class TaskTableModel(QAbstractTableModel):
    NameRole = Qt.UserRole + 1
    StatusRole = Qt.UserRole + 2
    TypeRole = Qt.UserRole + 3
    ProgressRole = Qt.UserRole + 4
    PriorityRole = Qt.UserRole + 5
    DurationRole = Qt.UserRole + 6
    UpdatedAtRole = Qt.UserRole + 7
    TaskIdRole = Qt.UserRole + 8

    def __init__(self, db_path: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._group_id = 0
        self._row_count = 0
        self._cache_profile = NORMAL_CACHE
        self._pages: OrderedDict[int, list[dict[str, Any]]] = OrderedDict()

    def roleNames(self) -> dict[int, bytes]:  # noqa: N802
        return {
            int(self.NameRole): b"name",
            int(self.StatusRole): b"status",
            int(self.TypeRole): b"taskType",
            int(self.ProgressRole): b"progress",
            int(self.PriorityRole): b"priority",
            int(self.DurationRole): b"duration",
            int(self.UpdatedAtRole): b"updatedAt",
            int(self.TaskIdRole): b"taskId",
        }

    def rowCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else self._row_count

    def columnCount(self, parent: QModelIndex = QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(TASK_COLUMNS)

    def group_id(self) -> int:
        return int(self._group_id)

    def data(self, index: QModelIndex, role: int = Qt.DisplayRole) -> Any:
        if not index.isValid() or not 0 <= index.row() < self._row_count:
            return None
        row = self._row_at(index.row())
        if row is None:
            return None
        column_name = TASK_COLUMNS[index.column()] if 0 <= index.column() < len(TASK_COLUMNS) else "name"
        if role == Qt.DisplayRole:
            if column_name == "progress":
                return f"{int(row.get(column_name, 0))}%"
            return row.get(column_name, "")
        role_map = {
            self.NameRole: "name",
            self.StatusRole: "status",
            self.TypeRole: "task_type",
            self.ProgressRole: "progress",
            self.PriorityRole: "priority",
            self.DurationRole: "duration",
            self.UpdatedAtRole: "updated_at",
            self.TaskIdRole: "id",
        }
        key = role_map.get(role)
        return row.get(key) if key else None

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.DisplayRole) -> Any:  # noqa: N802
        if role == Qt.DisplayRole and orientation == Qt.Horizontal and 0 <= section < len(TASK_HEADERS):
            return TASK_HEADERS[section]
        return None

    def set_low_memory(self, enabled: bool) -> None:
        profile = LOW_MEMORY_CACHE if enabled else NORMAL_CACHE
        if profile == self._cache_profile:
            return
        self._cache_profile = profile
        self.clear_cache()

    def set_group(self, group_id: int) -> None:
        group_id = int(group_id or 0)
        if group_id > 0:
            with _connect(self._db_path) as conn:
                count = conn.execute("SELECT COUNT(*) FROM tasks WHERE group_id = ?", (group_id,)).fetchone()[0]
        else:
            count = 0
        self.beginResetModel()
        self._group_id = group_id
        self._row_count = int(count)
        self._pages.clear()
        self.endResetModel()
        self.prefetch(0)

    def clear_cache(self) -> None:
        self._pages.clear()

    def reload(self) -> None:
        self.set_group(self._group_id)

    def prefetch(self, first_row: int) -> None:
        if self._row_count <= 0:
            return
        page = max(0, int(first_row) // self._cache_profile.page_size)
        self._ensure_page(page)
        if self._cache_profile.max_pages > 2:
            self._ensure_page(page + 1)

    def task_id_at(self, row_index: int) -> int:
        row = self._row_at(row_index)
        return int(row["id"]) if row else 0

    def task_type_at(self, row_index: int) -> str:
        row = self._row_at(row_index)
        return str(row.get("task_type", "default")) if row else "default"

    def _row_at(self, row_index: int) -> dict[str, Any] | None:
        if row_index < 0:
            return None
        page_index = row_index // self._cache_profile.page_size
        offset = row_index % self._cache_profile.page_size
        page = self._ensure_page(page_index)
        if 0 <= offset < len(page):
            return page[offset]
        return None

    def _ensure_page(self, page_index: int) -> list[dict[str, Any]]:
        if page_index in self._pages:
            self._pages.move_to_end(page_index)
            return self._pages[page_index]
        if self._group_id <= 0:
            return []
        offset = page_index * self._cache_profile.page_size
        with _connect(self._db_path) as conn:
            rows = conn.execute(
                """
                SELECT id, task_type, name, status, progress, priority, duration, updated_at
                FROM tasks
                WHERE group_id = ?
                ORDER BY id
                LIMIT ? OFFSET ?
                """,
                (self._group_id, self._cache_profile.page_size, offset),
            ).fetchall()
        page = [
            {
                "id": int(row[0]),
                "task_type": str(row[1]),
                "name": str(row[2]),
                "status": str(row[3]),
                "progress": int(row[4]),
                "priority": str(row[5]),
                "duration": str(row[6]),
                "updated_at": str(row[7]),
            }
            for row in rows
        ]
        self._pages[page_index] = page
        while len(self._pages) > self._cache_profile.max_pages:
            self._pages.popitem(last=False)
        return page


class TaskStore(QObject):
    groupChanged = Signal()
    busyChanged = Signal()
    statusMessageChanged = Signal()
    importFinished = Signal(bool, str)
    writeFinished = Signal(bool, str)

    def __init__(self, performance, parent: QObject | None = None, db_path: Path | None = None, settings=None) -> None:
        super().__init__(parent)
        self._db_path = Path(db_path) if db_path is not None else app_data_dir() / "data" / "tasks.db"
        _init_db(self._db_path)
        self._performance = performance
        self._settings = settings
        self._groups = TaskGroupModel(self._db_path, self)
        self._tasks = TaskTableModel(self._db_path, self)
        self._current_group_index = 0
        self._pending_group_id = 0
        self._busy = False
        self._status_message = ""
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="task-store")
        self._lock = threading.Lock()
        self._tasks.set_low_memory(bool(getattr(performance, "lowMemoryMode", False)))
        self.importFinished.connect(self._finish_import_on_gui_thread)
        self.writeFinished.connect(self._finish_write_on_gui_thread)
        self._restore_last_group()
        try:
            performance.lowMemoryModeChanged.connect(self._tasks.set_low_memory)
        except Exception:
            pass

    @Property(QObject, constant=True)
    def groupModel(self) -> QObject:
        return self._groups

    @Property(QObject, constant=True)
    def taskModel(self) -> QObject:
        return self._tasks

    @Property(int, notify=groupChanged)
    def currentGroupIndex(self) -> int:
        return self._current_group_index

    @Property(int, notify=groupChanged)
    def groupCount(self) -> int:
        return self._groups.rowCount()

    @Property(bool, notify=busyChanged)
    def busy(self) -> bool:
        return self._busy

    @Property(str, notify=statusMessageChanged)
    def statusMessage(self) -> str:
        return self._status_message

    @Slot(int)
    def selectGroup(self, index: int) -> None:
        count = self._groups.rowCount()
        if count <= 0:
            self._current_group_index = 0
            self._tasks.set_group(0)
            self.groupChanged.emit()
            return
        index = max(0, min(int(index), count - 1))
        self._current_group_index = index
        group_id = self._groups.group_id_at(index)
        self._tasks.set_group(group_id)
        if self._settings is not None and group_id > 0:
            self._settings.set_value_py("taskList/lastGroupId", group_id)
        self.groupChanged.emit()

    def _restore_last_group(self) -> None:
        group_index = 0
        if self._settings is not None:
            try:
                saved_group_id = int(self._settings.value_py("taskList/lastGroupId", 0) or 0)
            except Exception:
                saved_group_id = 0
            saved_index = self._groups.row_for_group_id(saved_group_id)
            if saved_index >= 0:
                group_index = saved_index
        self.selectGroup(group_index)

    @Slot(int)
    def prefetchAround(self, row: int) -> None:
        self._tasks.prefetch(max(0, int(row)))

    @Slot(int, result=int)
    def taskIdAt(self, row: int) -> int:
        return self._tasks.task_id_at(int(row))

    @Slot(int, result=str)
    def taskTypeAt(self, row: int) -> str:
        return self._tasks.task_type_at(int(row))

    @Slot(int, result="QVariant")
    def taskDetails(self, task_id: int) -> dict[str, Any]:
        try:
            with _connect(self._db_path) as conn:
                row = conn.execute(
                    """
                    SELECT id, task_type, name, status, progress, priority, duration, params_json, updated_at
                    FROM tasks
                    WHERE id = ?
                    """,
                    (int(task_id),),
                ).fetchone()
        except Exception:
            row = None
        if not row:
            return {
                "id": int(task_id),
                "taskType": "default",
                "name": "",
                "status": "",
                "progress": 0,
                "priority": "",
                "duration": "",
                "updatedAt": "",
            }
        return {
            "id": int(row[0]),
            "taskType": str(row[1]),
            "name": str(row[2]),
            "status": str(row[3]),
            "progress": int(row[4]),
            "priority": str(row[5]),
            "duration": str(row[6]),
            "params": _loads_params(row[7]),
            "updatedAt": str(row[8]),
        }

    @Slot(int, "QVariant")
    def saveTaskDetails(self, task_id: int, values) -> None:
        if int(task_id) <= 0:
            return
        data = to_python(values) or {}
        if not isinstance(data, dict):
            data = {}
        payload = self._task_payload_from_values(data)
        write_runtime_log(f"TaskStore.saveTaskDetails task_id={int(task_id)} name={payload['name']} type={payload['task_type']}")
        self._set_busy(True)
        self._set_status("正在保存任务")
        future = self._executor.submit(self._save_task_worker, int(task_id), payload)
        future.add_done_callback(self._emit_write_finished)

    @Slot("QVariant")
    def createTask(self, values) -> None:
        group_id = self._groups.group_id_at(self._current_group_index)
        if group_id <= 0:
            self._set_status("请先新建分组")
            return
        data = to_python(values) or {}
        if not isinstance(data, dict):
            data = {}
        payload = self._task_payload_from_values(data)
        count = _bounded_int(data.get("count", 1), 1, 1, 10000)
        self._set_busy(True)
        self._set_status(f"正在创建 {count} 条任务" if count > 1 else "正在创建任务")
        future = self._executor.submit(self._create_task_worker, group_id, payload, count)
        future.add_done_callback(self._emit_write_finished)

    @Slot(str, result="QVariant")
    def parseClipboardTask(self, text: str) -> dict[str, Any]:
        raw = str(text or "").strip()
        task_type = _task_type_from_text(raw)
        name = raw.splitlines()[0].strip() if raw else "剪贴板任务"
        params: dict[str, Any] = {}
        if task_type == "download":
            source = raw
            for prefix in ("url:", "download:", "import:"):
                if source.lower().startswith(prefix):
                    source = source[len(prefix) :].strip()
                    break
            params["source"] = source
        elif task_type == "script":
            script = raw
            for prefix in ("script:", "cmd:", "powershell:", "python:", "bash:"):
                if script.lower().startswith(prefix):
                    script = script[len(prefix) :].strip()
                    break
            params["script"] = script
        else:
            params["target"] = raw
        return {
            "taskType": task_type,
            "name": name[:120],
            "status": "待处理",
            "progress": 0,
            "priority": "普通",
            "duration": "-",
            "params": params,
        }

    @Slot()
    def addTask(self) -> None:
        group_id = self._groups.group_id_at(self._current_group_index)
        if group_id <= 0:
            self._set_status("请先新建分组")
            return
        self._set_busy(True)
        self._set_status("正在新建任务")
        future = self._executor.submit(self._add_task_worker, group_id)
        future.add_done_callback(self._emit_write_finished)

    @Slot()
    def addGroup(self) -> None:
        self._set_busy(True)
        self._set_status("正在新建分组")
        future = self._executor.submit(self._add_group_worker)
        future.add_done_callback(self._emit_write_finished)

    @Slot(int)
    def deleteGroupAt(self, index: int) -> None:
        group_id = self._groups.group_id_at(int(index))
        if group_id <= 0:
            return
        self._set_busy(True)
        self._set_status("正在删除分组")
        future = self._executor.submit(self._delete_group_worker, group_id)
        future.add_done_callback(self._emit_write_finished)

    @Slot("QVariant")
    def deleteGroupRows(self, rows) -> None:
        try:
            row_values = sorted({int(row) for row in to_python(rows) if int(row) >= 0})
        except Exception:
            row_values = []
        group_ids = self._groups.group_ids_at(row_values)
        if not group_ids:
            return
        self._set_busy(True)
        self._set_status("正在删除分组")
        future = self._executor.submit(self._delete_groups_worker, group_ids)
        future.add_done_callback(self._emit_write_finished)

    @Slot(int, int)
    def moveGroup(self, source_index: int, target_index: int) -> None:
        count = self._groups.rowCount()
        if count <= 1:
            return
        source = max(0, min(int(source_index), count - 1))
        target = max(0, min(int(target_index), count - 1))
        if source == target:
            return
        group_id = self._groups.group_id_at(source)
        if group_id <= 0:
            return
        self._pending_group_id = group_id
        self._set_busy(True)
        self._set_status("正在调整分组顺序")
        future = self._executor.submit(self._move_group_worker, group_id, target)
        future.add_done_callback(self._emit_write_finished)

    @Slot(int, str)
    def renameGroupAt(self, index: int, name: str) -> None:
        group_id = self._groups.group_id_at(int(index))
        next_name = str(name or "").strip()
        if group_id <= 0 or not next_name:
            return
        self._set_busy(True)
        self._set_status("正在重命名分组")
        future = self._executor.submit(self._rename_group_worker, group_id, next_name)
        future.add_done_callback(self._emit_write_finished)

    @Slot(int)
    def deleteTaskAt(self, row: int) -> None:
        task_id = self._tasks.task_id_at(int(row))
        if task_id <= 0:
            return
        self._set_busy(True)
        self._set_status("正在删除选中任务")
        future = self._executor.submit(self._delete_task_worker, task_id)
        future.add_done_callback(self._emit_write_finished)

    @Slot("QVariant")
    def deleteTaskRows(self, rows) -> None:
        try:
            row_values = sorted({int(row) for row in to_python(rows) if int(row) >= 0})
        except Exception:
            row_values = []
        task_ids = [self._tasks.task_id_at(row) for row in row_values]
        task_ids = [task_id for task_id in task_ids if task_id > 0]
        if not task_ids:
            return
        self._set_busy(True)
        self._set_status("正在删除选中任务")
        future = self._executor.submit(self._delete_tasks_worker, task_ids)
        future.add_done_callback(self._emit_write_finished)

    @Slot(str)
    def importFile(self, path: str) -> None:
        file_path = _normalize_path(path)
        if not file_path.exists():
            self._set_status("导入失败：文件不存在")
            return
        self._set_busy(True)
        self._set_status("正在导入 " + file_path.name)
        future = self._executor.submit(self._import_worker, file_path, bool(getattr(self._performance, "lowMemoryMode", False)))
        future.add_done_callback(self._emit_import_finished)

    @Slot()
    def refresh(self) -> None:
        self._groups.reload()
        self.selectGroup(min(self._current_group_index, max(0, self._groups.rowCount() - 1)))
        self._set_status("列表已刷新")

    @Slot()
    def clearCaches(self) -> None:
        self._tasks.clear_cache()

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _add_task_worker(self, group_id: int) -> tuple[bool, str]:
        try:
            with self._lock:
                with _connect(self._db_path) as conn:
                    count = int(conn.execute("SELECT COUNT(*) FROM tasks WHERE group_id = ?", (group_id,)).fetchone()[0])
                    task_type = ("default", "download", "script")[count % 3]
                    conn.execute(
                        """
                        INSERT INTO tasks(group_id, task_type, name, status, progress, priority, duration)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (group_id, task_type, "新建任务", "待处理", 0, "普通", "-"),
                    )
            return True, "已新建任务"
        except Exception as exc:
            return False, "新建失败：" + str(exc)

    def _task_payload_from_values(self, data: dict[str, Any]) -> dict[str, Any]:
        params = data.get("params", {})
        if not isinstance(params, dict):
            params = {}
        return {
            "task_type": str(data.get("taskType", data.get("task_type", "default")) or "default"),
            "name": str(data.get("name", "") or "").strip() or "未命名任务",
            "status": str(data.get("status", "") or "").strip() or "待处理",
            "progress": _safe_int(data.get("progress", 0), 0),
            "priority": str(data.get("priority", "") or "").strip() or "普通",
            "duration": str(data.get("duration", "") or "").strip() or "-",
            "params_json": json.dumps(params, ensure_ascii=False, separators=(",", ":")),
        }

    def _create_task_worker(self, group_id: int, payload: dict[str, Any], count: int = 1) -> tuple[bool, str]:
        try:
            total = max(1, min(10000, int(count or 1)))
            with self._lock:
                with _connect(self._db_path) as conn:
                    values = []
                    for index in range(total):
                        name = payload["name"] if total == 1 else f"{payload['name']} {index + 1}"
                        values.append(
                            (
                                group_id,
                                payload["task_type"],
                                name,
                                payload["status"],
                                int(payload["progress"]),
                                payload["priority"],
                                payload["duration"],
                                payload["params_json"],
                            )
                        )
                    conn.executemany(
                        """
                        INSERT INTO tasks(group_id, task_type, name, status, progress, priority, duration, params_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        values,
                    )
            return True, f"已创建 {total} 条任务" if total > 1 else "已创建任务"
        except Exception as exc:
            return False, "创建失败：" + str(exc)

    def _add_group_worker(self) -> tuple[bool, str]:
        try:
            with self._lock:
                with _connect(self._db_path) as conn:
                    order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM task_groups").fetchone()[0]
                    base_name = "新建分组"
                    name = base_name
                    suffix = 2
                    while conn.execute("SELECT 1 FROM task_groups WHERE name = ?", (name,)).fetchone():
                        name = f"{base_name} {suffix}"
                        suffix += 1
                    cursor = conn.execute("INSERT INTO task_groups(name, sort_order) VALUES (?, ?)", (name, int(order)))
                    self._pending_group_id = int(cursor.lastrowid)
            return True, "已新建分组"
        except Exception as exc:
            return False, "新建分组失败：" + str(exc)

    def _delete_group_worker(self, group_id: int) -> tuple[bool, str]:
        try:
            with self._lock:
                with _connect(self._db_path) as conn:
                    conn.execute("DELETE FROM task_groups WHERE id = ?", (group_id,))
            return True, "已删除分组"
        except Exception as exc:
            return False, "删除分组失败：" + str(exc)

    def _delete_groups_worker(self, group_ids: list[int]) -> tuple[bool, str]:
        try:
            ids = [int(group_id) for group_id in group_ids if int(group_id) > 0]
            with self._lock:
                with _connect(self._db_path) as conn:
                    conn.executemany("DELETE FROM task_groups WHERE id = ?", [(group_id,) for group_id in ids])
            return True, "已删除分组"
        except Exception as exc:
            return False, "删除分组失败：" + str(exc)

    def _move_group_worker(self, group_id: int, target_index: int) -> tuple[bool, str]:
        try:
            with self._lock:
                with _connect(self._db_path) as conn:
                    rows = conn.execute("SELECT id FROM task_groups ORDER BY sort_order, id").fetchall()
                    ids = [int(row[0]) for row in rows]
                    if int(group_id) not in ids:
                        return False, "调整失败：分组不存在"
                    ids.remove(int(group_id))
                    target = max(0, min(int(target_index), len(ids)))
                    ids.insert(target, int(group_id))
                    conn.executemany(
                        "UPDATE task_groups SET sort_order = ? WHERE id = ?",
                        [(index, item_id) for index, item_id in enumerate(ids)],
                    )
            return True, "已调整分组顺序"
        except Exception as exc:
            return False, "调整分组顺序失败：" + str(exc)

    def _rename_group_worker(self, group_id: int, name: str) -> tuple[bool, str]:
        try:
            with self._lock:
                with _connect(self._db_path) as conn:
                    conn.execute("UPDATE task_groups SET name = ? WHERE id = ?", (name, int(group_id)))
            return True, "已重命名分组"
        except sqlite3.IntegrityError:
            return False, "重命名失败：分组名已存在"
        except Exception as exc:
            return False, "重命名失败：" + str(exc)

    def _delete_task_worker(self, task_id: int) -> tuple[bool, str]:
        return self._delete_tasks_worker([task_id])

    def _delete_tasks_worker(self, task_ids: list[int]) -> tuple[bool, str]:
        try:
            with self._lock:
                with _connect(self._db_path) as conn:
                    conn.executemany("DELETE FROM tasks WHERE id = ?", [(int(task_id),) for task_id in task_ids])
            return True, f"已删除 {len(task_ids)} 条任务"
        except Exception as exc:
            return False, "删除失败：" + str(exc)

    def _save_task_worker(self, task_id: int, payload: dict[str, Any]) -> tuple[bool, str]:
        try:
            with self._lock:
                with _connect(self._db_path) as conn:
                    conn.execute(
                        """
                        UPDATE tasks
                        SET task_type = ?,
                            name = ?,
                            status = ?,
                            progress = ?,
                            priority = ?,
                            duration = ?,
                            params_json = ?,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?
                        """,
                        (
                            payload["task_type"],
                            payload["name"],
                            payload["status"],
                            int(payload["progress"]),
                            payload["priority"],
                            payload["duration"],
                            payload["params_json"],
                            int(task_id),
                        ),
                    )
            return True, "已保存任务"
        except Exception as exc:
            return False, "保存失败：" + str(exc)

    def _set_busy(self, value: bool) -> None:
        if self._busy == value:
            return
        self._busy = value
        self.busyChanged.emit()

    def _set_status(self, message: str) -> None:
        if self._status_message == message:
            return
        self._status_message = message
        self.statusMessageChanged.emit()

    def _import_worker(self, path: Path, low_memory: bool) -> tuple[bool, str]:
        try:
            group_name, rows = _load_import_rows(path)
            if not rows:
                return False, "导入失败：没有可导入的任务"
            with self._lock:
                with _connect(self._db_path) as conn:
                    existing = conn.execute("SELECT id FROM task_groups WHERE name = ?", (group_name,)).fetchone()
                    if existing:
                        group_id = int(existing[0])
                    else:
                        order = conn.execute("SELECT COALESCE(MAX(sort_order), 0) + 1 FROM task_groups").fetchone()[0]
                        cursor = conn.execute("INSERT INTO task_groups(name, sort_order) VALUES (?, ?)", (group_name, int(order)))
                        group_id = int(cursor.lastrowid)
                    self._pending_group_id = group_id
                    batch_size = 300 if low_memory else 900
                    for start in range(0, len(rows), batch_size):
                        batch = rows[start : start + batch_size]
                        conn.executemany(
                            """
                            INSERT INTO tasks(group_id, task_type, name, status, progress, priority, duration, updated_at)
                            VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(NULLIF(?, ''), CURRENT_TIMESTAMP))
                            """,
                            [
                                (
                                    group_id,
                                    row["task_type"],
                                    row["name"],
                                    row["status"],
                                    row["progress"],
                                    row["priority"],
                                    row["duration"],
                                    row["updated_at"],
                                )
                                for row in batch
                            ],
                        )
            return True, f"已导入 {len(rows)} 条任务"
        except Exception as exc:
            return False, "导入失败：" + str(exc)

    def _emit_import_finished(self, future) -> None:
        try:
            ok, message = future.result()
        except Exception as exc:
            ok, message = False, "导入失败：" + str(exc)
        self.importFinished.emit(bool(ok), str(message))

    def _emit_write_finished(self, future) -> None:
        try:
            ok, message = future.result()
        except Exception as exc:
            ok, message = False, "写入失败：" + str(exc)
        self.writeFinished.emit(bool(ok), str(message))

    @Slot(bool, str)
    def _finish_import_on_gui_thread(self, ok: bool, message: str) -> None:
        self._set_busy(False)
        self._groups.reload()
        if ok and self._pending_group_id > 0:
            pending_index = self._groups.row_for_group_id(self._pending_group_id)
            self._pending_group_id = 0
            self.selectGroup(pending_index if pending_index >= 0 else max(0, self._groups.rowCount() - 1))
        else:
            self.selectGroup(self._current_group_index)
        self._set_status(message)

    @Slot(bool, str)
    def _finish_write_on_gui_thread(self, ok: bool, message: str) -> None:
        self._set_busy(False)
        self._groups.reload()
        if self._pending_group_id > 0:
            pending_index = self._groups.row_for_group_id(self._pending_group_id)
            self._pending_group_id = 0
            self._current_group_index = pending_index if pending_index >= 0 else min(self._current_group_index, max(0, self._groups.rowCount() - 1))
        else:
            current_index = self._groups.row_for_group_id(self._tasks.group_id())
            self._current_group_index = current_index if current_index >= 0 else min(self._current_group_index, max(0, self._groups.rowCount() - 1))
        if self._groups.rowCount() <= 0:
            self._current_group_index = 0
        self._tasks.set_group(self._groups.group_id_at(self._current_group_index))
        self.groupChanged.emit()
        self._set_status(message)
