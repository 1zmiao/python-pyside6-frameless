from __future__ import annotations

import ctypes
import gc
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Property, QTimer, Slot
from PySide6.QtGui import QPixmapCache
from PySide6.QtQml import QQmlApplicationEngine

from .card_glow_provider import CardGlowImageProvider
from .dialog_service import DialogService
from .memory_tools import trim_process_memory
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
        self._card_glow_provider = CardGlowImageProvider()
        engine.addImageProvider("cardaccent", self._card_glow_provider)
        self._trim_timer = QTimer(self)
        self._trim_timer.setSingleShot(True)
        self._trim_timer.timeout.connect(self._performTrimMemory)
        try:
            self._theme.primaryColorCommitted.connect(lambda _c: self._card_glow_provider.clear_cache())
        except Exception:
            pass
        self._window = WindowController(self._settings, native_window_shell=native_window_shell)
        self._dialogs = DialogService(
            app=app,
            engine=engine,
            qml_dir=qml_dir,
            native_window_shell=native_window_shell,
            performance=self._performance,
            window_controller=self._window,
            bridge=self,
        )
        self._tray = TrayController(app=app, settings=self._settings, theme=self._theme, project_root=qml_dir.parent, parent=self, engine=engine, qml_dir=qml_dir)
        self._exiting = False
        self._quit_scheduled = False
        try:
            app.aboutToQuit.connect(self.shutdown)
        except Exception:
            pass
        QTimer.singleShot(1800, self.trimMemory)
        QTimer.singleShot(12000, self.trimMemory)

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

    @Property(bool, constant=True)
    def isSmokeExit(self) -> bool:
        return bool(os.environ.get("QROUNDEDFRAME_SMOKE_CLOSE_MS", "").strip())

    @Slot(str, result=str)
    def envValue(self, name: str) -> str:
        return os.environ.get(str(name or ""), "")

    @Slot()
    def exitApplication(self) -> None:
        if self._exiting:
            return
        self._exiting = True
        if self._useWindowsFastExit():
            self._fastExitProcess()
            return
        try:
            self._tray.shutdown()
        except Exception:
            pass
        try:
            self.shutdown()
        except Exception:
            pass
        self._cleanupExternalShadowsForExit()
        QTimer.singleShot(0, self._finishExitApplication)

    def _finishExitApplication(self) -> None:
        if self._quit_scheduled:
            return
        self._quit_scheduled = True
        QTimer.singleShot(0, self._quitApplication)

    def _quitApplication(self) -> None:
        if self._useWindowsFastExit():
            self._fastExitProcess()
            return
        self._app.quit()

    def _fastExitProcess(self) -> None:
        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                kernel32 = ctypes.windll.kernel32
                kernel32.TerminateProcess(kernel32.GetCurrentProcess(), 0)
            except Exception:
                pass
        os._exit(0)

    def _useWindowsFastExit(self) -> bool:
        return (
            sys.platform == "win32"
            and os.environ.get("QROUNDEDFRAME_DISABLE_FAST_EXIT", "").strip().lower() not in {"1", "true", "yes"}
        )

    def _prepareWindowsFastExit(self) -> None:
        try:
            self._tray.shutdown()
        except Exception:
            pass
        self._cleanupExternalShadowsForExit()
        self._hideWindowsForFastExit()

    def _windowsFastExitDelayMs(self) -> int:
        try:
            return max(0, min(2000, int(os.environ.get("QROUNDEDFRAME_WINDOWS_FAST_EXIT_MS", "0"))))
        except ValueError:
            return 0

    def _hideWindowsForFastExit(self) -> None:
        try:
            windows = list(self._app.allWindows())
        except Exception:
            windows = []
        for window in windows:
            try:
                window.hide()
            except Exception:
                pass

    def _cleanupExternalShadowsForExit(self) -> None:
        try:
            for window in self._app.allWindows():
                self._cleanupExternalShadowForExit(window)
        except Exception:
            pass
        try:
            for root in self._engine.rootObjects():
                self._cleanupExternalShadowForExit(root)
        except Exception:
            pass

    def _cleanupExternalShadowForExit(self, window) -> None:
        if window is None:
            return
        try:
            if hasattr(window, "cleanupExternalShadow"):
                window.cleanupExternalShadow()
        except Exception:
            pass
        try:
            root = getattr(window, "rootObject", lambda: None)()
            if root is not None:
                try:
                    if hasattr(root, "cleanupExternalShadow"):
                        root.cleanupExternalShadow()
                except Exception:
                    pass
        except Exception:
            pass

    @Slot()
    def trimMemory(self) -> None:
        # Coalesce repeated cleanup requests from page switching, popups,
        # theme animations and child-window teardown. Doing the actual trim on
        # the next idle beat avoids small UI stalls while still letting Windows
        # drop warmed caches shortly after interactions settle.
        self._trim_timer.start(650)

    @Slot()
    def trimMemoryNow(self) -> None:
        self._trim_timer.stop()
        self._performTrimMemory()

    def _performTrimMemory(self) -> None:
        collect_qml = True
        try:
            self._engine.trimComponentCache()
        except Exception:
            pass
        try:
            self._card_glow_provider.clear_cache()
        except Exception:
            pass
        try:
            QPixmapCache.clear()
        except Exception:
            pass
        try:
            for window in self._app.allWindows():
                visible = True
                try:
                    visible = bool(window.isVisible())
                except Exception:
                    pass
                if not visible and hasattr(window, "releaseResources"):
                    window.releaseResources()
        except Exception:
            pass
        try:
            self._performance.collectGarbage()
        except Exception:
            gc.collect()
        trim_process_memory(self._engine, collect_qml=collect_qml, empty_working_set=False)

    @Slot()
    def shutdown(self) -> None:
        try:
            self._dialogs.shutdown()
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
