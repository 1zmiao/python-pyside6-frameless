from __future__ import annotations

import ctypes
import gc
import os
import secrets
from pathlib import Path

from PySide6.QtCore import QObject, Property, Signal, Slot

from .memory_tools import trim_process_memory
from .settings_store import SettingsStore
from .util import app_data_dir


class PerformanceController(QObject):
    resourceProfileChanged = Signal(str)
    effectiveProfileChanged = Signal(str)
    lowMemoryModeChanged = Signal(bool)
    developerUnlockedChanged = Signal(bool)

    _VALID_PROFILES = {"auto", "normal", "low-memory"}
    _LOW_MEMORY_AUTO_LIMIT_MB = 4096

    def __init__(self, settings: SettingsStore, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._developer_key_file = app_data_dir() / "config" / "developer.key"
        self._resource_profile = self._normalize_profile(settings.value_py("performance/resourceProfile", None))
        legacy_low = settings.value_py("performance/lowMemoryMode", None)
        if legacy_low is not None and settings.value_py("performance/resourceProfile", None) is None:
            self._resource_profile = "low-memory" if bool(legacy_low) else "normal"
            self._settings.set_value_py("performance/resourceProfile", self._resource_profile)
        self._effective_profile = self._compute_effective_profile()
        self._low_memory_mode = self._effective_profile == "low-memory"
        self._developer_unlocked = self._developer_key_file.exists()
        try:
            settings.changed.connect(self._on_setting_changed)
        except Exception:
            pass

    @Property(str, notify=resourceProfileChanged)
    def resourceProfile(self) -> str:
        return self._resource_profile

    @Property(str, notify=effectiveProfileChanged)
    def effectiveProfile(self) -> str:
        return self._effective_profile

    @Property(bool, notify=lowMemoryModeChanged)
    def lowMemoryMode(self) -> bool:
        return self._low_memory_mode

    @Property(bool, notify=developerUnlockedChanged)
    def developerUnlocked(self) -> bool:
        return self._developer_unlocked

    @Property(bool, constant=True)
    def developerKeyPresent(self) -> bool:
        return self._developer_key_file.exists()

    @Property(str, constant=True)
    def developerKeyPath(self) -> str:
        return str(self._developer_key_file)

    @Slot(str)
    def setResourceProfile(self, profile: str) -> None:
        profile = self._normalize_profile(profile)
        if self._resource_profile == profile:
            return
        self._resource_profile = profile
        self._settings.set_value_py("performance/resourceProfile", profile)
        self.resourceProfileChanged.emit(profile)
        self._refresh_effective_profile()

    @Slot(bool)
    def setLowMemoryMode(self, enabled: bool) -> None:
        self.setResourceProfile("low-memory" if bool(enabled) else "normal")

    @Slot(str, result=bool)
    def unlockDeveloperMode(self, password: str) -> bool:
        ok = self._developer_key_file.exists() or str(password) == self._developer_password()
        if self._developer_unlocked != ok:
            self._developer_unlocked = ok
            self.developerUnlockedChanged.emit(ok)
        return ok

    @Slot()
    def lockDeveloperMode(self) -> None:
        if self._developer_key_file.exists():
            return
        if self._developer_unlocked:
            self._developer_unlocked = False
            self.developerUnlockedChanged.emit(False)

    @Slot()
    def collectGarbage(self) -> None:
        trim_process_memory()

    @Slot(result=int)
    def totalMemoryMb(self) -> int:
        return int(_total_memory_mb())

    def _normalize_profile(self, value) -> str:
        profile = str(value or "auto").strip().lower()
        return profile if profile in self._VALID_PROFILES else "auto"

    def _compute_effective_profile(self) -> str:
        if self._resource_profile != "auto":
            return self._resource_profile
        total_mb = _total_memory_mb()
        if total_mb > 0 and total_mb <= self._LOW_MEMORY_AUTO_LIMIT_MB:
            return "low-memory"
        return "normal"

    def _refresh_effective_profile(self) -> None:
        next_effective = self._compute_effective_profile()
        next_low = next_effective == "low-memory"
        if self._effective_profile != next_effective:
            self._effective_profile = next_effective
            self.effectiveProfileChanged.emit(next_effective)
        if self._low_memory_mode != next_low:
            self._low_memory_mode = next_low
            self.lowMemoryModeChanged.emit(next_low)
        if next_low:
            gc.collect()

    def _developer_password(self) -> str:
        return os.environ.get("FRAMELESS_DEVELOPER_PASSWORD") or str(self._settings.value_py("developer/password", "code"))

    def _on_setting_changed(self, key: str, value) -> None:
        if key == "performance/resourceProfile":
            profile = self._normalize_profile(value)
            if self._resource_profile != profile:
                self._resource_profile = profile
                self.resourceProfileChanged.emit(profile)
                self._refresh_effective_profile()
        elif key == "performance/lowMemoryMode":
            self.setResourceProfile("low-memory" if bool(value) else "normal")


def _total_memory_mb() -> int:
    if os.name == "nt":
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("sullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]
        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(status)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys // (1024 * 1024))
        return 0
    try:
        pages = os.sysconf("SC_PHYS_PAGES")
        page_size = os.sysconf("SC_PAGE_SIZE")
        return int((pages * page_size) // (1024 * 1024))
    except Exception:
        return 0


def ensure_local_developer_key() -> Path:
    key_file = app_data_dir() / "config" / "developer.key"
    key_file.parent.mkdir(parents=True, exist_ok=True)
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    return key_file
