from __future__ import annotations

import gc
import os
import weakref
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Slot
from PySide6.QtQml import QQmlApplicationEngine, QQmlComponent

from app.page_registry import page_definition, page_source_url, page_title
from app.runtime_logging import write_runtime_log

from .card_glow_provider import CardGlowImageProvider
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
        self._child_engine: QQmlApplicationEngine | None = None
        self._child_card_glow_provider: CardGlowImageProvider | None = None
        self._child_components: dict[Path, QQmlComponent] = {}
        self._connected_window_ids: set[int] = set()
        self._native_child_window_manager: QObject | None = None
        self._closing_all = False
        self._shutting_down = False
        write_runtime_log(f"DialogService shared_child_engine_default={self._use_shared_child_engine()}")

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
            self._forget_window(id(existing))
        page_source = self._page_source(page_key)
        if self._open_native_child(parent_window, page_key, page_source, props):
            return
        obj = None
        if obj is None:
            child_source = self._qml_dir / "window" / ("NativeChildWindow.qml" if self._use_native_child_windows() else "ChildWindow.qml")
            use_child_engine = self._use_shared_child_engine()
            write_runtime_log(f"DialogService.openChild page={page_key} engine={'child' if use_child_engine else 'main'}")
            component = self._component_for(child_source, child_engine=use_child_engine)
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
        obj.setProperty("pageTitle", page_title(page_key, child_default=True))
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

    @Slot(str)
    def prepareChild(self, page_key: str) -> None:
        if self._shutting_down or self._closing_all:
            return
        page_key = str(page_key or "")
        if not page_key:
            return
        try:
            child_source = self._qml_dir / "window" / ("NativeChildWindow.qml" if self._use_native_child_windows() else "ChildWindow.qml")
            use_child_engine = self._use_shared_child_engine()
            self._component_for(child_source, child_engine=use_child_engine)
            self._page_component_for(page_key, child_engine=use_child_engine)
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
        # Keep the C++ native child manager as an experimental path only.
        # The default path uses Python-owned QML child windows until the native manager proves clean close/release behavior.
        if os.environ.get("QROUNDEDFRAME_EXPERIMENTAL_USE_NATIVE_CHILD_MANAGER", "").strip().lower() not in {"1", "true", "yes"}:
            return False
        if not self._native_child_window_manager or not self._use_native_child_windows():
            return False
        child_source = self._qml_dir / "window" / "NativeChildWindow.qml"
        window_key = f"child-{page_key}"
        try:
            obj = self._native_child_window_manager.openChild(
                QUrl.fromLocalFile(str(child_source)),
                QUrl(page_source),
                page_title(page_key, child_default=True),
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

    def _use_shared_child_engine(self) -> bool:
        return os.environ.get("QROUNDEDFRAME_DISABLE_SHARED_CHILD_ENGINE", "").strip().lower() not in {"1", "true", "yes"}

    def _shared_child_engine(self) -> QQmlApplicationEngine | None:
        if self._child_engine is not None:
            return self._child_engine
        child_engine = QQmlApplicationEngine(self)
        try:
            child_engine.setImportPathList(self._engine.importPathList())
        except Exception:
            child_engine.addImportPath(str(self._qml_dir))
        provider = CardGlowImageProvider()
        try:
            child_engine.addImageProvider("cardaccent", provider)
        except Exception:
            pass
        try:
            child_engine.rootContext().setContextProperty("App", self._bridge)
        except Exception:
            pass
        self._child_engine = child_engine
        self._child_card_glow_provider = provider
        write_runtime_log("DialogService child QQmlApplicationEngine created")
        return child_engine

    def _component_for(self, source: Path, *, child_engine: bool = False) -> QQmlComponent | None:
        component_cache = self._child_components if child_engine else self._components
        component = component_cache.get(source)
        if component is not None:
            return component
        engine = self._shared_child_engine() if child_engine else self._engine
        if engine is None:
            return None
        component = QQmlComponent(engine, QUrl.fromLocalFile(str(source)), engine if child_engine else self)
        if component.isError():
            print(f"Failed to load child component: {source}")
            for error in component.errors():
                print(error.toString())
            return None
        component_cache[source] = component
        return component

    def _page_component_for(self, page_key: str, *, child_engine: bool = False) -> QQmlComponent | None:
        try:
            page = page_definition(page_key, child_default=True)
        except Exception:
            return None
        source = self._qml_dir / "pages" / page.qml_file
        return self._component_for(source, child_engine=child_engine)

    def trim_child_engine_caches(self, *, clear_components: bool = False) -> None:
        if self._child_card_glow_provider is not None:
            try:
                self._child_card_glow_provider.clear_cache()
            except Exception:
                pass
        child_engine = self._child_engine
        if child_engine is None:
            return
        if clear_components:
            try:
                child_engine.clearComponentCache()
            except Exception:
                pass
        try:
            child_engine.trimComponentCache()
        except Exception:
            pass
        try:
            child_engine.collectGarbage()
        except Exception:
            pass

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
                lambda event_type, payload, obj_ref=obj_ref, obj_id=obj_id: self._handle_window_event(obj_id, obj_ref(), event_type, payload)
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
            self._destroy_shared_child_engine()
            return
        windows = list(self._windows.values())
        for obj in windows:
            self._forget_window(id(obj))
            self._prepare_child_window_for_app_exit(obj)
        self._destroy_shared_child_engine()

    def _finish_close_all(self) -> None:
        if self._shutting_down:
            return
        self._closing_all = False

    def _page_source(self, page_key: str) -> str:
        # 独立子窗口由 Python 管生命周期，所以页面 URL 在 Python 侧统一解析。
        # 不把页面路由重复散落到多个 QML 文件，避免新增页面时漏改。
        return page_source_url(self._qml_dir, page_key, child_default=True)

    def _handle_window_event(self, obj_id: int, obj: QObject, event_type: str, payload=None) -> None:
        if str(event_type) != "closing":
            return
        self._forget_window(obj_id)
        destroy_requested = False
        try:
            data = to_python(payload) or {}
            destroy_requested = bool(data.get("destroy", False)) if isinstance(data, dict) else False
        except Exception:
            destroy_requested = False
        if obj is not None and destroy_requested:
            self._destroy_closed_child_window(obj)
        self._schedule_post_release_trim(deep=False)

    def _destroy_closed_child_window(self, obj: QObject) -> None:
        obj_id = id(obj)
        if obj_id in self._releasing_windows:
            return
        self._releasing_windows.add(obj_id)
        try:
            delete_later = getattr(obj, "deleteLater", None)
            if callable(delete_later):
                QTimer.singleShot(0, delete_later)
        except Exception:
            self._releasing_windows.discard(obj_id)

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
        all_children_closed = not self._windows
        if all_children_closed:
            self._destroy_shared_child_engine()
        self._schedule_post_release_trim(deep=all_children_closed)

    def _destroy_shared_child_engine(self) -> None:
        child_engine = self._child_engine
        if child_engine is None:
            return
        write_runtime_log("DialogService child QQmlApplicationEngine destroying")
        self._child_engine = None
        self._child_components.clear()
        provider = self._child_card_glow_provider
        self._child_card_glow_provider = None
        try:
            if provider is not None:
                provider.clear_cache()
        except Exception:
            pass
        try:
            child_engine.clearComponentCache()
        except Exception:
            pass
        try:
            child_engine.trimComponentCache()
        except Exception:
            pass
        try:
            child_engine.collectGarbage()
        except Exception:
            pass
        try:
            child_engine.deleteLater()
        except Exception:
            pass

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
        # Do not destroy a top-level QML Window synchronously inside the close signal stack.
        # Release page/graphics resources first, then queue deleteLater on the next event-loop turn.
        # This lets the shared child engine be destroyed after the last independent child window closes.
        self._releasing_windows.discard(obj_id)
        QTimer.singleShot(0, lambda obj=obj, obj_id=obj_id: self._delete_released_child_window(obj, obj_id))
        self._schedule_post_release_trim()

    def _delete_released_child_window(self, obj: QObject, obj_id: int) -> None:
        try:
            obj.deleteLater()
        except Exception:
            self._forget_window(obj_id)
            self._releasing_windows.discard(obj_id)
            if not self._windows:
                self._destroy_shared_child_engine()
            self._schedule_post_release_trim(deep=True)

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

    def _schedule_post_release_trim(self, *, deep: bool = False) -> None:
        if deep and self._bridge is not None:
            try:
                deep_trim = getattr(self._bridge, "trimMemoryAfterChildDestroy", None)
                if callable(deep_trim):
                    QTimer.singleShot(0, deep_trim)
                    return
            except Exception:
                pass
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
