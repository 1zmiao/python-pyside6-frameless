from __future__ import annotations

import gc
import os
import weakref
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Slot
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

from .memory_tools import trim_process_memory
from .util import to_python


class DialogService(QObject):
    def __init__(
        self,
        app,
        engine: QQmlApplicationEngine,
        qml_dir: Path,
        parent=None,
        native_window_shell: bool = False,
        performance=None,
        window_controller=None,
        bridge=None,
    ):
        super().__init__(parent)
        self._app = app
        self._engine = engine
        self._qml_dir = qml_dir
        self._bridge = bridge if bridge is not None else parent
        self._native_window_shell = bool(native_window_shell)
        self._performance = performance
        self._window_controller = window_controller
        self._windows: dict[int, QObject] = {}
        self._page_windows: dict[str, QObject] = {}
        self._releasing_windows: set[int] = set()
        self._components: dict[Path, QQmlComponent] = {}
        self._connected_window_ids: set[int] = set()
        self._native_child_window_manager: QObject | None = None
        self._closing_all = False
        self._shutting_down = False
        self._titles = {
            "settings": "设置",
            "tools": "工具",
            "update": "更新",
            "about": "关于",
            "home": "首页",
        }

    @Slot(QObject, str, "QVariant")
    def openChild(self, parent_window, page_key: str, props=None) -> None:
        if self._shutting_down or self._closing_all:
            return
        props = to_python(props) or {}
        existing = self._page_windows.get(page_key)
        if existing is not None:
            try:
                if bool(existing.property("visible")):
                    self._destroy_child_window(id(existing), page_key, existing)
                    return
            except Exception:
                pass
            self._destroy_child_window(id(existing), page_key, existing)
        page_source = self._page_source(page_key)
        if self._open_native_child(parent_window, page_key, page_source, props):
            return
        obj = None
        if obj is None:
            child_source = self._qml_dir / "window" / ("NativeChildWindow.qml" if self._use_native_child_windows() else "ChildWindow.qml")
            component = self._component_for(child_source)
            if component is None:
                return
            obj = self._create_child_object(component)
            if obj is None:
                print(f"Failed to create child window: {child_source}")
                for error in component.errors():
                    print(error.toString())
                return
            self._connect_window_signals(obj)

        try:
            if hasattr(obj, "prepareContent"):
                obj.prepareContent(page_source)
            else:
                obj.setProperty("pageSource", page_source)
        except Exception:
            obj.setProperty("pageSource", page_source)
        obj.setProperty("pageTitle", self._titles.get(page_key, page_key.title()))
        obj.setProperty("windowKey", f"child-{page_key}")
        try:
            obj.setProperty("alwaysOnTop", False)
        except Exception:
            pass
        if parent_window is not None:
            obj.setProperty("parentWindow", parent_window)
        if isinstance(props, dict):
            for key, value in props.items():
                try:
                    obj.setProperty(str(key), value)
                except Exception:
                    pass

        obj_id = id(obj)
        self._windows[obj_id] = obj
        self._page_windows[page_key] = obj

        try:
            # Apply geometry and persisted state before the first show so the
            # external shadow is created once at the final window rectangle.
            if hasattr(obj, "applyParentWindow"):
                obj.applyParentWindow()
            if hasattr(obj, "restorePersistedWindowState"):
                obj.restorePersistedWindowState()
            obj.show()
        except Exception:
            pass


    def set_native_window_shell(self, enabled: bool) -> None:
        self._native_window_shell = bool(enabled)

    @Slot(QObject)
    def setNativeChildWindowManager(self, manager: QObject | None) -> None:
        self._native_child_window_manager = manager

    def _use_native_child_windows(self) -> bool:
        return bool(self._native_window_shell)

    def _open_native_child(self, parent_window, page_key: str, page_source: str, props: dict) -> bool:
        if os.environ.get("QROUNDEDFRAME_USE_NATIVE_CHILD_MANAGER", "").strip().lower() not in {"1", "true", "yes"}:
            return False
        if not self._native_child_window_manager or not self._use_native_child_windows():
            return False
        child_source = self._qml_dir / "window" / "NativeChildWindow.qml"
        window_key = f"child-{page_key}"
        try:
            obj = self._native_child_window_manager.openChild(
                QUrl.fromLocalFile(str(child_source)),
                QUrl(page_source),
                self._titles.get(page_key, page_key.title()),
                window_key,
                parent_window,
                props,
            )
        except Exception as exc:
            print(f"Failed to open native child through C++ manager: {exc}")
            return False
        if obj is None:
            return False
        obj_id = id(obj)
        self._connect_window_signals(obj)
        self._windows[obj_id] = obj
        self._page_windows[page_key] = obj
        return True

    def _component_for(self, source: Path) -> QQmlComponent | None:
        component = self._components.get(source)
        if component is not None:
            return component
        component = QQmlComponent(self._engine, QUrl.fromLocalFile(str(source)), self)
        if component.isError():
            print(f"Failed to load child component: {source}")
            for error in component.errors():
                print(error.toString())
            return None
        self._components[source] = component
        return component

    def _create_child_object(self, component: QQmlComponent) -> QObject | None:
        try:
            obj = component.createWithInitialProperties({"bridge": self._bridge})
        except AttributeError:
            obj = component.create()
            if obj is not None:
                obj.setProperty("bridge", self._bridge)
        except Exception:
            obj = component.create()
            if obj is not None:
                obj.setProperty("bridge", self._bridge)
        return obj

    def _connect_window_signals(self, obj: QObject) -> None:
        obj_id = id(obj)
        if obj_id in self._connected_window_ids:
            return
        self._connected_window_ids.add(obj_id)
        try:
            obj.destroyed.connect(lambda *_args, obj_id=obj_id: self._handle_window_destroyed(obj_id))
        except Exception:
            pass
        obj_ref = weakref.ref(obj)
        try:
            obj.windowEvent.connect(
                lambda event_type, _payload, obj_ref=obj_ref, obj_id=obj_id: self._handle_window_event(obj_id, obj_ref(), event_type)
            )
        except Exception:
            pass

    @Slot()
    def closeAll(self) -> None:
        if self._closing_all:
            return
        self._closing_all = True
        windows = list(self._windows.values())
        for obj in windows:
            self._request_child_close(obj)
        QTimer.singleShot(0, self._finish_close_all)

    @Slot(QObject)
    def closeChildWindow(self, obj: QObject | None) -> None:
        if obj is None:
            return
        obj_id = id(obj)
        page_key = self._page_key_for_obj(obj_id)
        self._destroy_child_window(obj_id, page_key, obj)

    @Slot()
    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._closing_all = True
        if self._native_child_window_manager:
            try:
                self._native_child_window_manager.closeAll()
            except Exception:
                pass
            self._windows.clear()
            self._page_windows.clear()
            return
        windows = list(self._windows.values())
        for obj in windows:
            self._forget_window(id(obj))
            self._prepare_child_window_for_app_exit(obj)

    def _finish_close_all(self) -> None:
        if self._shutting_down:
            return
        self._closing_all = False

    def _page_source(self, page_key: str) -> str:
        mapping = {
            "home": "HomePage.qml",
            "settings": "SettingsPage.qml",
            "tools": "ToolsPage.qml",
            "update": "UpdatePage.qml",
            "about": "AboutPage.qml",
        }
        filename = mapping.get(page_key, "AboutPage.qml")
        return QUrl.fromLocalFile(str(self._qml_dir / "pages" / filename)).toString()

    def _handle_window_event(self, obj_id: int, obj: QObject, event_type: str) -> None:
        if str(event_type) != "closing":
            return
        self._forget_window(obj_id)
        self._schedule_post_release_trim()

    def _destroy_child_window(self, obj_id: int, page_key: str, obj: QObject | None) -> None:
        if obj is not None:
            self._request_child_close(obj)
        else:
            self._forget_window(obj_id)
        QTimer.singleShot(120, self._trim_engine_cache)
        QTimer.singleShot(180, self._collect_garbage)

    def _request_child_close(self, obj: QObject | None) -> None:
        if obj is None:
            return
        try:
            request_close = getattr(obj, "requestCloseFromController", None)
            if callable(request_close):
                request_close()
                return
        except Exception:
            pass
        try:
            close = getattr(obj, "close", None)
            if callable(close):
                close()
                return
        except Exception:
            pass
        self._forget_window(id(obj))
        self._release_child_window(obj)

    def _page_key_for_obj(self, obj_id: int) -> str:
        for key, value in list(self._page_windows.items()):
            if id(value) == obj_id:
                return key
        return ""

    def _forget_window(self, obj_id: int, destroyed: bool = False) -> None:
        self._windows.pop(obj_id, None)
        for key, value in list(self._page_windows.items()):
            if id(value) == obj_id:
                self._page_windows.pop(key, None)
        if destroyed:
            self._connected_window_ids.discard(obj_id)

    def _handle_window_destroyed(self, obj_id: int) -> None:
        self._forget_window(obj_id, destroyed=True)
        self._releasing_windows.discard(obj_id)
        self._schedule_post_release_trim()

    def _release_child_window(self, obj: QObject) -> None:
        obj_id = id(obj)
        if obj_id in self._releasing_windows:
            return
        self._releasing_windows.add(obj_id)
        try:
            if self._window_controller and hasattr(self._window_controller, "saveNativeManagedWindowState"):
                self._window_controller.saveNativeManagedWindowState(obj)
        except Exception:
            pass
        try:
            if hasattr(obj, "cleanupExternalShadow"):
                obj.cleanupExternalShadow()
        except Exception:
            pass
        try:
            if hasattr(obj, "releaseContent"):
                obj.releaseContent()
        except Exception:
            pass
        try:
            obj.setProperty("visible", False)
        except Exception:
            pass
        try:
            hide = getattr(obj, "hide", None)
            if callable(hide):
                hide()
        except Exception:
            pass
        try:
            release = getattr(obj, "releaseResources", None)
            if callable(release):
                release()
        except Exception:
            pass
        self._releasing_windows.discard(obj_id)
        self._schedule_post_release_trim()

    def _prepare_child_window_for_app_exit(self, obj: QObject) -> None:
        obj_id = id(obj)
        if obj_id in self._releasing_windows:
            return
        self._releasing_windows.add(obj_id)
        try:
            if self._window_controller and hasattr(self._window_controller, "saveNativeManagedWindowState"):
                self._window_controller.saveNativeManagedWindowState(obj)
        except Exception:
            pass
        try:
            if hasattr(obj, "cleanupExternalShadow"):
                obj.cleanupExternalShadow()
        except Exception:
            pass
        try:
            if hasattr(obj, "releaseContent"):
                obj.releaseContent()
        except Exception:
            pass

    def _schedule_post_release_trim(self) -> None:
        QTimer.singleShot(120, self._trim_engine_cache)
        QTimer.singleShot(180, self._collect_garbage)

    def _trim_engine_cache(self) -> None:
        try:
            self._engine.trimComponentCache()
        except Exception:
            pass

    def _collect_garbage(self) -> None:
        try:
            if self._performance and hasattr(self._performance, "collectGarbage"):
                self._performance.collectGarbage()
        except Exception:
            pass
        try:
            trim_process_memory(self._engine, collect_qml=True, empty_working_set=False)
        except Exception:
            gc.collect()
