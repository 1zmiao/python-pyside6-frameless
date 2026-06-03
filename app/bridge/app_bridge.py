from __future__ import annotations

import ctypes
import gc
import sys
from pathlib import Path

from PySide6.QtCore import QObject, Property, Slot
from PySide6.QtQml import QQmlApplicationEngine

from .card_glow_provider import CardGlowImageProvider
from .dialog_service import DialogService
from .performance_controller import PerformanceController
from .secret_store import SecretStore
from .settings_store import SettingsStore
from .theme_controller import ThemeController
from .tray_controller import TrayController
from .window_controller import WindowController


class AppBridge(QObject):
    def __init__(self, app, engine: QQmlApplicationEngine, qml_dir: Path, parent=None, native_window_shell: bool = False):
        super().__init__(parent)
        self._app = app
        self._engine = engine
        self._settings = SettingsStore()
        self._secrets = SecretStore(password=None)
        self._performance = PerformanceController(self._settings, parent=self)
        self._theme = ThemeController(self._settings)
        engine.addImageProvider("cardaccent", CardGlowImageProvider())
        self._window = WindowController(self._settings, native_window_shell=native_window_shell)
        self._dialogs = DialogService(
            engine=engine,
            qml_dir=qml_dir,
            native_window_shell=native_window_shell,
            performance=self._performance,
        )
        self._tray = TrayController(app=app, settings=self._settings, theme=self._theme, project_root=qml_dir.parent, parent=self, engine=engine, qml_dir=qml_dir)
        try:
            app.aboutToQuit.connect(self.shutdown)
        except Exception:
            pass

    @Property(QObject, constant=True)
    def settings(self):
        return self._settings

    @Property(QObject, constant=True)
    def secrets(self):
        return self._secrets

    @Property(QObject, constant=True)
    def performance(self):
        return self._performance

    @Property(QObject, constant=True)
    def theme(self):
        return self._theme

    @Property(QObject, constant=True)
    def window(self):
        return self._window

    @Property(QObject, constant=True)
    def dialogs(self):
        return self._dialogs

    @Property(QObject, constant=True)
    def tray(self):
        return self._tray


    @Slot()
    def trimMemory(self) -> None:
        try:
            self._engine.trimComponentCache()
        except Exception:
            pass
        try:
            self._performance.collectGarbage()
        except Exception:
            gc.collect()
        if sys.platform == "win32":
            try:
                ctypes.windll.psapi.EmptyWorkingSet(ctypes.windll.kernel32.GetCurrentProcess())
            except Exception:
                pass

    @Slot()
    def shutdown(self) -> None:
        try:
            self._dialogs.closeAll()
        except Exception:
            pass
        try:
            self._window.shutdown()
        except Exception:
            pass
        try:
            self._tray.shutdown()
        except Exception:
            pass

    def set_native_window_shell(self, enabled: bool) -> None:
        self._window.set_native_window_shell(bool(enabled))
        self._dialogs.set_native_window_shell(bool(enabled))

    @Slot(str)
    def copyToClipboard(self, text: str) -> None:
        clipboard = self._app.clipboard()
        clipboard.setText(str(text))

    @Slot(str)
    def copyText(self, text: str) -> None:
        clipboard = self._app.clipboard()
        if clipboard is not None:
            clipboard.setText(str(text))