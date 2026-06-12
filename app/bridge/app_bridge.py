from __future__ import annotations

import ctypes
import gc
import os
import sys
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, Property, QTimer, Signal, Slot
from PySide6.QtGui import QPixmapCache
from PySide6.QtQml import QQmlApplicationEngine

from app.page_registry import page_icon, page_qml_source, page_title
from app.runtime_logging import flush_runtime_log, write_runtime_log
from app.memory_snapshot import current_process_memory

from .card_glow_provider import CardGlowImageProvider
from .dialog_service import DialogService
from .memory_tools import trim_process_memory
from .performance_controller import PerformanceController
from .secret_store import SecretStore
from .settings_store import SettingsStore
from .task_store import TaskStore
from .theme_controller import ThemeController
from .tray_controller import TrayController
from .util import to_python
from .window_controller import WindowController


class AppBridge(QObject):
    prepareChildRequested = Signal(str, str)
    openChildRequested = Signal(str, str, "QVariant")

    def __init__(self, app, engine: QQmlApplicationEngine, qml_dir: Path, parent=None, native_window_shell: bool = False):
        super().__init__(parent)
        self._app = app
        self._engine = engine
        self._settings = SettingsStore()
        self._secrets = SecretStore(password=None)
        self._performance = PerformanceController(self._settings, parent=self)
        self._task_store = TaskStore(self._performance, parent=self, settings=self._settings)
        self._theme = ThemeController(self._settings)
        self._card_glow_provider = CardGlowImageProvider()
        engine.addImageProvider("cardaccent", self._card_glow_provider)
        self._trim_timer = QTimer(self)
        self._trim_timer.setSingleShot(True)
        self._trim_timer.timeout.connect(self._performTrimMemory)
        self._card_glow_clear_timer = QTimer(self)
        self._card_glow_clear_timer.setSingleShot(True)
        self._card_glow_clear_timer.setInterval(1600)
        self._card_glow_clear_timer.timeout.connect(self._clearCardGlowCache)
        self._page_settled_trim_timer = QTimer(self)
        self._page_settled_trim_timer.setSingleShot(True)
        self._page_settled_trim_timer.setInterval(1800)
        self._page_settled_trim_timer.timeout.connect(self._trimMemoryAfterPageSettled)
        self._auto_memory_trim_timer = QTimer(self)
        self._auto_memory_trim_timer.setInterval(10000)
        self._auto_memory_trim_timer.timeout.connect(self._checkAutoMemoryTrim)
        self._trimming_memory = False
        try:
            self._theme.primaryColorCommitted.connect(lambda _c: self._scheduleCardGlowCacheClear())
            self._theme.modeChanged.connect(lambda _m: self._scheduleCardGlowCacheClear())
        except Exception:
            pass
        try:
            self._settings.changed.connect(lambda key, _value: self._onSettingsChanged(str(key)))
            self._performance.resourceProfileChanged.connect(lambda _profile: self._onResourceProfileChanged())
            self._performance.lowMemoryModeChanged.connect(lambda _enabled: self._onResourceProfileChanged())
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
        self.logMemorySample("bridge_ready")
        self._syncAutoMemoryTrimTimer()
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

    @Property(QObject, constant=True)
    def taskStore(self):
        return self._task_store

    @Property(bool, constant=True)
    def isSmokeExit(self) -> bool:
        return bool(os.environ.get("QROUNDEDFRAME_SMOKE_CLOSE_MS", "").strip())

    @Slot(str, result=str)
    def envValue(self, name: str) -> str:
        return os.environ.get(str(name or ""), "")

    @Slot(str, result=str)
    def pageTitle(self, page_key: str) -> str:
        return page_title(page_key)

    @Slot(str, result=str)
    def pageSource(self, page_key: str) -> str:
        return page_qml_source(page_key)

    @Slot(str, result=str)
    def pageIcon(self, page_key: str) -> str:
        return page_icon(page_key)

    @Slot(str, str, "QVariant")
    def requestOpenChild(self, page_key: str, mode: str = "auto", props=None) -> None:
        safe_props = to_python(props) or {}
        if not isinstance(safe_props, dict):
            safe_props = {}
        self.openChildRequested.emit(str(page_key or ""), str(mode or "auto"), safe_props)

    @Slot(str, str)
    def prepareOpenChild(self, page_key: str, mode: str = "auto") -> None:
        self.prepareChildRequested.emit(str(page_key or ""), str(mode or "auto"))

    @Slot()
    def exitApplication(self) -> None:
        if self._exiting:
            write_runtime_log("AppBridge.exitApplication ignored: already exiting")
            return
        self._exiting = True
        write_runtime_log(f"AppBridge.exitApplication entered fast_exit={self._useWindowsFastExit()}")
        if self._useWindowsFastExit():
            self._fastExitProcess()
            return
        try:
            self._tray.shutdown()
        except Exception:
            pass
        try:
            self._task_store.shutdown()
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
        write_runtime_log(f"AppBridge._quitApplication fast_exit={self._useWindowsFastExit()}")
        if self._useWindowsFastExit():
            self._fastExitProcess()
            return
        self._app.quit()

    def _fastExitProcess(self) -> None:
        write_runtime_log("AppBridge._fastExitProcess entered")
        self._saveWindowsForFastExit()
        try:
            sys.stdout.flush()
        except Exception:
            pass
        try:
            sys.stderr.flush()
        except Exception:
            pass
        flush_runtime_log()
        if sys.platform == "win32":
            try:
                # Windows 上正常析构 Qt Quick/DXGI 偶发 QThreadStorage/QDxgiVSyncService 告警。
                # 这里先保存窗口状态和日志，再直接结束进程；不要改回半析构退出流程。
                kernel32 = ctypes.windll.kernel32
                kernel32.GetCurrentProcess.restype = ctypes.c_void_p
                kernel32.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
                kernel32.TerminateProcess.restype = ctypes.c_int
                handle = kernel32.GetCurrentProcess()
                write_runtime_log(f"AppBridge._fastExitProcess TerminateProcess handle={handle}")
                flush_runtime_log()
                kernel32.TerminateProcess(handle, 0)
            except Exception as exc:
                write_runtime_log(f"AppBridge._fastExitProcess TerminateProcess failed: {exc!r}")
                flush_runtime_log()
        write_runtime_log("AppBridge._fastExitProcess os._exit fallback")
        flush_runtime_log()
        os._exit(0)

    def _saveWindowsForFastExit(self) -> None:
        seen: set[int] = set()

        def save_window(win) -> None:
            if win is None:
                return
            try:
                ident = id(win)
                if ident in seen:
                    return
                seen.add(ident)
                key = str(win.property("windowKey") or "")
                if not key:
                    return
                self._window.saveNativeManagedWindowState(win)
                write_runtime_log(f"saved fast-exit window state key={key}")
            except Exception as exc:
                write_runtime_log(f"save fast-exit window state failed: {exc!r}")

        try:
            for win in self._app.allWindows():
                save_window(win)
        except Exception:
            pass
        try:
            for root in self._engine.rootObjects():
                save_window(root)
        except Exception:
            pass

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

    @Slot()
    def trimMemoryAfterChildDestroy(self) -> None:
        self._trim_timer.stop()
        # 独立子窗口销毁后才允许做深度清理。不要把 clearComponentCache 放到滚动、
        # 菜单、缩放这类高频路径，否则会把交互换成反复重新编译 QML。
        self._performTrimMemory(force_clear_component_cache=True, empty_working_set=True, reason="child_destroy")
        QTimer.singleShot(900, lambda: self._performTrimMemory(force_clear_component_cache=True, empty_working_set=True, reason="child_destroy_late"))

    @Slot()
    def trimMemoryAfterInlineWindowsClosed(self) -> None:
        self._trim_timer.stop()
        self._performTrimMemory(force_clear_component_cache=True, empty_working_set=False, reason="inline_destroy")
        QTimer.singleShot(900, lambda: self._performTrimMemory(force_clear_component_cache=True, empty_working_set=False, reason="inline_destroy_late"))

    @Slot()
    def trimMemoryAfterPageSettled(self) -> None:
        self._page_settled_trim_timer.start()

    @Slot()
    def trimResizeMemory(self) -> None:
        self._trim_timer.stop()
        self._performTrimMemory(resize_cleanup=True)

    def _scheduleCardGlowCacheClear(self) -> None:
        self._card_glow_clear_timer.start()

    def _clearCardGlowCache(self) -> None:
        try:
            self._card_glow_provider.clear_cache()
        except Exception:
            pass
        try:
            if str(self._theme.mode) == "light":
                self._performTrimMemory(empty_working_set=True, reason="card_glow_disabled")
        except Exception:
            pass

    def _trimMemoryAfterPageSettled(self) -> None:
        self._performTrimMemory(empty_working_set=True, reason="page_settled")

    def _autoMemoryTrimEnabled(self) -> bool:
        try:
            return bool(self._settings.value_py("performance/autoTrimMemory", False))
        except Exception:
            return False

    def _syncAutoMemoryTrimTimer(self) -> None:
        if self._autoMemoryTrimEnabled():
            if not self._auto_memory_trim_timer.isActive():
                self._auto_memory_trim_timer.start()
        else:
            self._auto_memory_trim_timer.stop()

    def _onSettingsChanged(self, key: str) -> None:
        if key == "performance/autoTrimMemory":
            self._syncAutoMemoryTrimTimer()

    def _checkAutoMemoryTrim(self) -> None:
        if not self._autoMemoryTrimEnabled() or self._trimming_memory:
            return
        sample = current_process_memory()
        ws_private = float(sample.get("ws_private", 0.0) or 0.0)
        threshold = 120.0 if self._performance.lowMemoryMode else 180.0
        write_runtime_log(
            f"auto memory trim check ws_private_mb={ws_private:.1f}"
            f" threshold_mb={threshold:.1f}"
            f" low_memory={self._performance.lowMemoryMode}"
        )
        if ws_private >= threshold:
            self._performTrimMemory(
                force_clear_component_cache=self._performance.lowMemoryMode,
                empty_working_set=True,
                reason="auto_threshold",
            )

    @Slot(str)
    def logMemorySample(self, label: str = "") -> None:
        sample = current_process_memory()
        write_runtime_log(
            "memory"
            f" label={str(label or 'sample')}"
            f" rss_mb={sample.get('rss', 0.0):.1f}"
            f" private_mb={sample.get('private', 0.0):.1f}"
            f" ws_private_mb={sample.get('ws_private', 0.0):.1f}"
        )

    @Slot(result="QVariant")
    def memorySample(self):
        return current_process_memory()

    @Slot(str)
    def logRuntime(self, message: str) -> None:
        write_runtime_log(str(message or ""))

    def _performTrimMemory(
        self,
        *,
        resize_cleanup: bool = False,
        force_clear_component_cache: bool = False,
        empty_working_set: bool = False,
        reason: str = "",
    ) -> None:
        if self._trimming_memory:
            return
        self._trimming_memory = True
        try:
            before_label = "before_resize_trim" if resize_cleanup else f"before_trim_{reason}" if reason else "before_trim"
            after_label = "after_resize_trim" if resize_cleanup else f"after_trim_{reason}" if reason else "after_trim"
            self.logMemorySample(before_label)
            collect_qml = True
            clear_component_cache = (
                force_clear_component_cache
                or
                self._performance.lowMemoryMode
                or os.environ.get("QROUNDEDFRAME_CLEAR_QML_COMPONENT_CACHE", "").strip().lower() in {"1", "true", "yes"}
            )
            if clear_component_cache:
                try:
                    # 低内存档位下允许清 QML 组件缓存。这个缓存不是页面对象泄漏，
                    # 而是 Qt 为下次加载保留的编译/类型数据；清掉能降低切页后的长期
                    # private commit，但重新进入页面会多一点加载成本，所以普通档不默认做。
                    self._engine.clearComponentCache()
                except Exception:
                    pass
            try:
                self._engine.trimComponentCache()
            except Exception:
                pass
            try:
                self._card_glow_provider.clear_cache()
            except Exception:
                pass
            try:
                self._dialogs.trim_child_engine_caches(clear_components=clear_component_cache)
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
                    release_visible = os.environ.get("QROUNDEDFRAME_RELEASE_VISIBLE_QUICK_RESOURCES", "").strip().lower() in {"1", "true", "yes"}
                    release_after_resize = (
                        resize_cleanup
                        and os.environ.get("QROUNDEDFRAME_RELEASE_VISIBLE_QUICK_RESOURCES_AFTER_RESIZE", "").strip().lower()
                        in {"1", "true", "yes"}
                    )
                    if visible and (release_visible or release_after_resize) and hasattr(window, "releaseResources"):
                        window.releaseResources()
                    if not visible and hasattr(window, "releaseResources"):
                        window.releaseResources()
            except Exception:
                pass
            try:
                self._performance.collectGarbage()
            except Exception:
                gc.collect()
            trim_process_memory(self._engine, collect_qml=collect_qml, empty_working_set=empty_working_set)
            self.logMemorySample(after_label)
        finally:
            self._trimming_memory = False

    def _onResourceProfileChanged(self) -> None:
        # 切换低内存档会触发 QML 绑定、图片尺寸和主题资源重新求值，
        # 峰值可能先上涨。档位变化后主动安排一次低频清理，避免用户
        # 手动切完后一直停留在切换瞬间的热缓存状态。
        write_runtime_log(f"resource profile changed low_memory={self._performance.lowMemoryMode}")
        QTimer.singleShot(900, self.trimMemoryNow)
        QTimer.singleShot(2400, self.trimMemoryNow)

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
