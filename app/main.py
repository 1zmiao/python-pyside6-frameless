from __future__ import annotations

import os
import sys
import json
from pathlib import Path

from PySide6.QtCore import QCoreApplication, QObject, QEvent, QTimer, QUrl
from PySide6.QtGui import QGuiApplication, QPixmapCache, QSurfaceFormat
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickWindow, QSGRendererInterface
from PySide6.QtQuickControls2 import QQuickStyle

from app.bridge.app_bridge import AppBridge
from app.bridge.util import runtime_root
from app.native.runtime import configure_native_runtime, native_runtime_available, native_runtime_variant
from app.window_policy import current_window_policy

_SMOKE_TIMERS: list[QTimer] = []


def linux_tray_enabled_by_settings() -> bool:
    if not sys.platform.startswith("linux"):
        return False
    try:
        settings_file = Path(__file__).resolve().parents[1] / "user_data" / "config" / "settings.json"
        data = json.loads(settings_file.read_text(encoding="utf-8"))
        window = data.get("window", {}) if isinstance(data, dict) else {}
        return bool(window.get("closeToTray", window.get("minimizeToTray", False)))
    except Exception:
        return False


def set_linux_process_name(name: str) -> None:
    if not sys.platform.startswith("linux"):
        return
    try:
        import ctypes

        libc = ctypes.CDLL(None)
        pr_set_name = 15
        libc.prctl(pr_set_name, name.encode("utf-8")[:15], 0, 0, 0)
    except Exception:
        pass


class QuickContextMenuFilter(QObject):
    """Suppress built-in QQuick text context menus.

    The QML controls provide their own AppContextMenu. Native QWidget/QMenu
    context menus, including the tray fallback on platforms that use one, are
    not affected because the filter only accepts QQuick* objects.
    """

    def eventFilter(self, obj, event):  # noqa: N802 - Qt override name
        try:
            if event.type() == QEvent.Type.ContextMenu:
                class_name = obj.metaObject().className() if obj is not None else ""
                if "QQuick" in class_name:
                    return True
        except Exception:
            pass
        return super().eventFilter(obj, event)


def schedule_smoke_close(root_objects) -> None:
    value = os.environ.get("QROUNDEDFRAME_SMOKE_CLOSE_MS", "").strip()
    if not value:
        return
    try:
        interval = max(0, int(value))
    except ValueError:
        return
    if not root_objects:
        return
    root = root_objects[0]

    def bridge_for_root():
        bridge = getattr(root, "_bridge", None)
        if bridge is not None:
            return bridge
        try:
            return root.property("bridge")
        except Exception:
            return None

    child_page = os.environ.get("QROUNDEDFRAME_SMOKE_CHILD_PAGE", "").strip()
    if child_page:
        child_close_ms = os.environ.get("QROUNDEDFRAME_SMOKE_CHILD_CLOSE_MS", "").strip()

        def print_smoke_window_state(label: str) -> None:
            try:
                windows = []
                for window in QCoreApplication.instance().allWindows():
                    try:
                        window_key = str(window.property("windowKey") or "")
                        visible = bool(window.isVisible()) if hasattr(window, "isVisible") else False
                        class_name = window.metaObject().className() if window is not None else ""
                        object_name = str(window.objectName() or "")
                        windows.append(f"{class_name}/{object_name}/{window_key}:{visible}")
                    except Exception:
                        windows.append("<invalid>")
                roots = []
                bridge = bridge_for_root()
                engine = getattr(bridge, "_engine", None) if bridge is not None else None
                if engine is not None:
                    for obj in engine.rootObjects():
                        try:
                            roots.append(str(obj.property("windowKey") or ""))
                        except Exception:
                            roots.append("<invalid>")
                print(f"smoke state {label}: windows={windows} roots={roots}", flush=True)
            except Exception as exc:
                print(f"smoke state {label} failed: {exc}", flush=True)

        def open_child() -> None:
            try:
                bridge = bridge_for_root()
                if bridge is not None and hasattr(bridge, "dialogs"):
                    bridge.dialogs.openChild(root, child_page, {})
                    print(f"smoke child opened: {child_page}", flush=True)
            except Exception as exc:
                print(f"smoke child open failed: {exc}", flush=True)

        child_timer = QTimer(QCoreApplication.instance())
        child_timer.setSingleShot(True)
        child_timer.timeout.connect(open_child)
        child_timer.start(max(0, min(interval - 250, 700)))
        _SMOKE_TIMERS.append(child_timer)

        if child_close_ms:
            try:
                child_close_interval = max(0, int(child_close_ms))
            except ValueError:
                child_close_interval = 0

            if child_close_interval > 0:
                def close_child() -> None:
                    try:
                        bridge = bridge_for_root()
                        if bridge is not None and hasattr(bridge, "dialogs"):
                            if os.environ.get("QROUNDEDFRAME_SMOKE_CHILD_CLOSE_MODE", "").strip().lower() == "window":
                                candidates = []
                                print("smoke child window scan starting", flush=True)
                                for window in QCoreApplication.instance().allWindows():
                                    try:
                                        window_key = str(window.property("windowKey") or "")
                                        visible = bool(window.isVisible()) if hasattr(window, "isVisible") else False
                                        class_name = window.metaObject().className() if window is not None else ""
                                        object_name = str(window.objectName() or "")
                                        print(f"smoke child window seen: {class_name}/{object_name}/{window_key}:{visible}", flush=True)
                                        if window_key.startswith("child-"):
                                            candidates.append((not visible, window))
                                    except Exception:
                                        pass
                                candidates.sort(key=lambda item: item[0])
                                if candidates:
                                    window = candidates[0][1]
                                    request_close = getattr(window, "requestCloseFromController", None)
                                    if callable(request_close):
                                        print("smoke child requestCloseFromController calling", flush=True)
                                        request_close()
                                        print("smoke child requestCloseFromController returned", flush=True)
                                    else:
                                        print("smoke child window.close calling", flush=True)
                                        window.close()
                                        print("smoke child window.close returned", flush=True)
                                else:
                                    print("smoke child window.close skipped", flush=True)
                            else:
                                bridge.dialogs.closeAll()
                                print("smoke child closeAll returned", flush=True)
                            QTimer.singleShot(450, lambda: print_smoke_window_state("child_close_450ms"))
                            QTimer.singleShot(1600, lambda: print_smoke_window_state("child_close_1600ms"))
                    except Exception as exc:
                        print(f"smoke child close failed: {exc}", flush=True)

                child_close_timer = QTimer(QCoreApplication.instance())
                child_close_timer.setSingleShot(True)
                child_close_timer.timeout.connect(close_child)
                child_close_timer.start(child_close_interval)
                _SMOKE_TIMERS.append(child_close_timer)
    print(f"smoke close scheduled after {interval} ms", flush=True)

    def close_root() -> None:
        print("smoke close firing", flush=True)
        used_bridge_exit = False
        try:
            bridge = bridge_for_root()
            if bridge is not None and hasattr(bridge, "exitApplication"):
                print("smoke App.exitApplication calling", flush=True)
                bridge.exitApplication()
                used_bridge_exit = True
                print("smoke App.exitApplication returned", flush=True)
            else:
                print("smoke root.close calling", flush=True)
                root.close()
                print("smoke root.close returned", flush=True)
        except Exception as exc:
            print(f"smoke root.close failed: {exc}", flush=True)
        if not used_bridge_exit:
            QCoreApplication.exit(0)

    timer = QTimer(QCoreApplication.instance())
    timer.setSingleShot(True)
    timer.timeout.connect(close_root)
    timer.start(interval)
    _SMOKE_TIMERS.append(timer)


def should_use_qwindowkit_shell(window_policy, project_root: Path) -> bool:
    """Return whether the top-level QML window should own the HWND.

    Prefer the top-level QML/QWindowKit shell whenever the native runtime is
    available.  It keeps the window to the expected two-layer model: native
    agent owns HWND behavior, QML owns content.  The QWidget/QQuickWidget host
    remains a fallback only when the QWindowKit shell cannot be loaded.
    """

    if not native_runtime_available(project_root):
        return False
    if not window_policy.native_shell_preferred:
        return False
    return True


def run_event_loop(app, engine: QQmlApplicationEngine | None = None) -> int:
    result = app.exec()
    if os.environ.get("QROUNDEDFRAME_SMOKE_CLOSE_MS", "").strip():
        print(f"smoke app.exec returned {result}", flush=True)
    return result


def main() -> int:
    set_linux_process_name("QRoundedFrame")

    # Avoid stale compiled QML cache when users replace this template folder during development.
    os.environ.setdefault("QML_DISABLE_DISK_CACHE", "1")
    # Leave QWindowKit's DwmFlush resize workaround enabled by default. It is
    # part of the native resize path and reduces D3D/VM backing-store flashes.
    if sys.platform == "win32":
        # Match QWindowKit's QML example: avoid Qt's D3D vblank helper thread,
        # which can outlive a fast Windows shutdown path and print DXGI cleanup
        # warnings on process exit.
        os.environ.setdefault("QT_D3D_NO_VBLANK_THREAD", "1")
    # Keep transparent rounded QML windows antialiased without allocating multisample render targets on every top-level Qt Quick scene graph.
    fmt = QSurfaceFormat()
    fmt.setSamples(0)
    if sys.platform == "win32":
        if os.environ.get("QROUNDEDFRAME_DISABLE_QUICK_ALPHA_BUFFER", "").strip().lower() in {"1", "true", "yes", "on"}:
            fmt.setAlphaBufferSize(0)
        else:
            fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    if sys.platform == "win32":
        QQuickWindow.setDefaultAlphaBuffer(
            os.environ.get("QROUNDEDFRAME_DISABLE_QUICK_ALPHA_BUFFER", "").strip().lower()
            not in {"1", "true", "yes", "on"}
        )
        if os.environ.get("QROUNDEDFRAME_FORCE_SOFTWARE_QUICK", "").strip().lower() in {"1", "true", "yes"}:
            QQuickWindow.setGraphicsApi(QSGRendererInterface.GraphicsApi.Software)

    if sys.platform == "win32" or linux_tray_enabled_by_settings():
        from PySide6.QtWidgets import QApplication

        app = QApplication(sys.argv)
    else:
        app = QGuiApplication(sys.argv)

    # Keep Qt's global pixmap cache bounded. The UI uses many small themed
    # images and generated accents; without a cap, routine interactions can
    # grow the working set and keep it warm for too long.
    QPixmapCache.setCacheLimit(int(os.environ.get("QROUNDEDFRAME_PIXMAP_CACHE_KB", "8192")))

    QCoreApplication.setOrganizationName("QRoundedFrame")
    QCoreApplication.setOrganizationDomain("qroundedframe.local")
    QCoreApplication.setApplicationName("QRoundedFrame")

    QQuickStyle.setStyle("Basic")
    app.installEventFilter(QuickContextMenuFilter(app))
    if os.environ.get("QROUNDEDFRAME_SMOKE_CLOSE_MS", "").strip():
        try:
            app.aboutToQuit.connect(lambda: print("smoke app aboutToQuit", flush=True))
        except Exception:
            pass
        try:
            app.lastWindowClosed.connect(lambda: print("smoke app lastWindowClosed", flush=True))
        except Exception:
            pass

    project_root = runtime_root()
    qml_dir = project_root / "qml"

    engine = QQmlApplicationEngine()
    engine.addImportPath(str(qml_dir))
    native_runtime_configured = configure_native_runtime(engine, project_root)

    window_policy = current_window_policy()
    use_qwindowkit_shell = should_use_qwindowkit_shell(window_policy, project_root)
    use_native_child_shell = native_runtime_available(project_root) and window_policy.native_shell_preferred
    if os.environ.get("FRAMELESS_DEBUG_WINDOW_POLICY", "").strip().lower() in {"1", "true", "yes"}:
        try:
            print("Window policy:", window_policy)
            print("Native runtime variant:", native_runtime_variant())
            print("Native runtime available:", use_native_child_shell)
            print("QWindowKit main shell:", use_qwindowkit_shell)
            print("Native runtime configured:", native_runtime_configured)
            from app.native.runtime import native_import_candidates

            print("Native import candidates:", [str(path) for path in native_import_candidates(project_root) if path.exists()])
        except Exception as exc:
            print("Window policy debug failed:", exc)

    bridge = AppBridge(app=app, engine=engine, qml_dir=qml_dir, parent=app, native_window_shell=use_native_child_shell)
    engine.rootContext().setContextProperty("App", bridge)

    if use_qwindowkit_shell:
        engine.load(QUrl.fromLocalFile(str(qml_dir / "NativeAppMain.qml")))
        if engine.rootObjects():
            schedule_smoke_close(engine.rootObjects())
            result = run_event_loop(app, engine)
            if os.environ.get("QROUNDEDFRAME_SMOKE_CLOSE_MS", "").strip():
                print(f"smoke main returning {result}", flush=True)
            return result
        bridge.set_native_window_shell(False)

    if sys.platform == "win32":
        from app.windows_host import NativeFramelessHost

        # The main window is a QWidget host on the Win10 custom-shadow path,
        # while native child windows are QWindow/QML roots. Letting Qt quit
        # when the last QWindow closes can tear down the app while the QWidget
        # main host is still alive.
        try:
            app.setQuitOnLastWindowClosed(False)
        except Exception:
            pass

        host = NativeFramelessHost(app=app, engine=engine, bridge=bridge, qml_dir=qml_dir)
        host.show()
        schedule_smoke_close([host])
    else:
        engine.load(QUrl.fromLocalFile(str(qml_dir / "MainWindow.qml")))
        if not engine.rootObjects():
            return 1
        schedule_smoke_close(engine.rootObjects())

    result = run_event_loop(app, engine)
    if os.environ.get("QROUNDEDFRAME_SMOKE_CLOSE_MS", "").strip():
        print(f"smoke main returning {result}", flush=True)
    return result


if __name__ == "__main__":
    exit_code = main()
    if os.environ.get("QROUNDEDFRAME_SMOKE_CLOSE_MS", "").strip():
        print(f"smoke SystemExit {exit_code}", flush=True)
    if os.name == "nt" and os.environ.get("QROUNDEDFRAME_DISABLE_RUN_FAST_EXIT", "").strip().lower() not in {"1", "true", "yes"}:
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(int(exit_code))
    raise SystemExit(exit_code)
