from __future__ import annotations

import ctypes
import os
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QObject, Property, QRect, Qt, QTimer, QUrl, Signal, Slot, QPropertyAnimation
from PySide6.QtGui import QColor, QGuiApplication, QSurfaceFormat, QCursor, QPainterPath, QRegion, QPalette, QPainter
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QWidget, QApplication

from .runtime_logging import write_runtime_log
from .windows_compat import is_windows_11_or_newer, use_custom_window_shadow


if sys.platform == "win32":
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

    WM_WINDOWPOSCHANGING = 0x0046
    WM_WINDOWPOSCHANGED = 0x0047
    WM_SIZING = 0x0214
    WM_MOVING = 0x0216
    WM_SYSCOMMAND = 0x0112
    SC_MOVE = 0xF010
    SC_MAXIMIZE = 0xF030
    SC_RESTORE = 0xF120
    SW_SHOWNORMAL = 1
    SW_RESTORE = 9
    HTCAPTION = 2
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020
    SWP_NOOWNERZORDER = 0x0200
    DWMWA_WINDOW_CORNER_PREFERENCE = 33
    DWMWA_BORDER_COLOR = 34
    DWMWA_NCRENDERING_POLICY = 2
    DWMNCRP_DISABLED = 1
    DWMNCRP_ENABLED = 2
    DWMWCP_DEFAULT = 0
    DWMWCP_ROUND = 2
    DWMWA_COLOR_NONE = 0xFFFFFFFE
    GWL_STYLE = -16
    WS_THICKFRAME = 0x00040000
    WS_CAPTION = 0x00C00000
    WS_SYSMENU = 0x00080000
    WS_MINIMIZEBOX = 0x00020000
    WS_MAXIMIZEBOX = 0x00010000
    VK_LBUTTON = 0x01

    class MARGINS(ctypes.Structure):
        _fields_ = [("cxLeftWidth", ctypes.c_int), ("cxRightWidth", ctypes.c_int), ("cyTopHeight", ctypes.c_int), ("cyBottomHeight", ctypes.c_int)]

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
        ]

    class WINDOWPLACEMENT(ctypes.Structure):
        _fields_ = [
            ("length", wintypes.UINT),
            ("flags", wintypes.UINT),
            ("showCmd", wintypes.UINT),
            ("ptMinPosition", wintypes.POINT),
            ("ptMaxPosition", wintypes.POINT),
            ("rcNormalPosition", wintypes.RECT),
        ]

else:
    MSG = None


class _QuickContentHost:
    def __init__(self, owner: QWidget, engine, qml_dir: Path, bridge, clear_color: QColor) -> None:
        self._source_loaded = False
        widget = QQuickWidget(engine, owner)
        widget.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        widget.setClearColor(clear_color)
        widget.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        widget.setAutoFillBackground(True)
        widget.engine().addImportPath(str(qml_dir))
        widget.rootContext().setContextProperty("NativeHost", owner)
        widget.rootContext().setContextProperty("App", bridge)
        self.widget = widget

    def setSource(self, url: QUrl) -> None:
        if self._source_loaded:
            return
        self.widget.setSource(url)
        self._source_loaded = True

    def rootObject(self):
        return self.widget.rootObject()

    def setClearColor(self, color: QColor) -> None:
        self.widget.setClearColor(color)

    def setPaletteColor(self, color: QColor) -> None:
        try:
            palette = self.widget.palette()
            palette.setColor(QPalette.ColorRole.Window, color)
            self.widget.setPalette(palette)
        except Exception:
            pass

    def update(self) -> None:
        self.widget.update()

    def geometry(self) -> QRect:
        return self.widget.geometry()

    def setGeometry(self, rect: QRect) -> None:
        self.widget.setGeometry(rect)

    def width(self) -> int:
        return int(self.widget.width())


class NativeFramelessHost(QWidget):
    """Windows-only native frameless host for the QML scene.

    The QML scene remains responsible for visuals, menus, pages, theme and storage.
    The QWidget HWND owns resize/move/maximize/snap behavior so Windows can handle
    drag-release, Aero Snap and maximize-drag-restore without Qt Quick geometry hacks.
    """

    maximizedChanged = Signal()
    activeChanged = Signal()
    geometryChanged = Signal()
    alwaysOnTopChanged = Signal(bool)
    toastRequested = Signal(str)
    snapPreviewChanged = Signal(str, int, int, int, int, bool)
    nativeShown = Signal()

    def __init__(
        self,
        app: QApplication,
        engine=None,
        bridge=None,
        qml_dir: Path | None = None,
        parent=None,
        *,
        window_key: str = "main",
        title: str = "QRoundedFrame",
        qml_source: str = "NativeMainContent.qml",
        page_source: str = "",
        page_title: str = "",
        default_geometry: QRect | None = None,
        minimum_size: tuple[int, int] = (640, 420),
        quit_on_close: bool = True,
        close_to_tray: bool = True,
        show_pin_button: bool = False,
    ):
        super().__init__(parent)
        self._app = app
        self._bridge = bridge
        self._qml_dir = Path(qml_dir) if qml_dir is not None else Path(__file__).resolve().parents[1] / "qml"
        if engine is None:
            raise ValueError("NativeFramelessHost requires the shared QQmlApplicationEngine")
        self._engine = engine
        self._window_key = str(window_key or "window")
        self._settings_key = f"windows/{self._window_key}"
        self._is_main_window = self._window_key == "main"
        self._quit_on_close = bool(quit_on_close)
        self._close_to_tray = bool(close_to_tray)
        self._closing_from_dialog_service = False
        self._page_source = str(page_source or "")
        self._page_title = str(page_title or title or "")
        self._show_pin_button = bool(show_pin_button)
        self._source_file = str(qml_source or "NativeMainContent.qml")
        default_rect = QRect(default_geometry) if default_geometry is not None else QRect(160, 90, 1080, 700)
        self._resize_border = 3
        self._default_geometry = QRect(default_rect)
        self._normal_geometry = QRect(default_rect)
        self._normal_frame_geometry = QRect(self._normal_geometry)
        self._move_state: dict | None = None
        self._title_bar_height = 36
        self._caption_regions: list[tuple[int, int]] = []
        self._snap_preview_rect: QRect | None = None
        self._snap_preview_type: str | None = None
        self._snap_margin = 14
        self._always_on_top = False
        self._title = str(title or self._page_title or "QRoundedFrame")
        self.setProperty("windowKey", self._window_key)
        self.setProperty("pageSource", self._page_source)
        self.setProperty("pageTitle", self._page_title)
        self._custom_shadow_enabled = use_custom_window_shadow()
        self._last_shadow_inset = 0
        self._corner_radius = 0
        self._native_widget_agent_ready = False
        self._native_size_move_active = False
        self._live_resize_guard_px = max(0, min(16, int(os.environ.get("QROUNDEDFRAME_LIVE_RESIZE_GUARD_PX", "0") or "0")))
        self._shell_background_color = self._initial_shell_background_color()
        self._shell_background_animation = QPropertyAnimation(self, b"animatedShellBackground", self)
        self._shell_background_animation.setDuration(180)

        self.setMinimumSize(max(1, int(minimum_size[0])), max(1, int(minimum_size[1])))
        self.resize(max(self.minimumWidth(), default_rect.width()), max(self.minimumHeight(), default_rect.height()))
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if self._custom_shadow_enabled:
            flags |= Qt.WindowType.NoDropShadowWindowHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        if not self._is_main_window:
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setAutoFillBackground(True)

        self._backing = QWidget(self)
        self._backing.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self._backing.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, False)
        self._backing.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)
        self._backing.setAutoFillBackground(True)
        self._set_widget_palette_color(self._backing, self._shell_background_color)
        self._backing.lower()

        source_url = QUrl.fromLocalFile(str(self._qml_dir / self._source_file))
        write_runtime_log("NativeFramelessHost content_host=QQuickWidget")
        self._quick_host = _QuickContentHost(
            self,
            self._engine,
            self._qml_dir,
            bridge,
            self._shell_background_color,
        )
        self._quick = self._quick_host.widget

        self._move_timer = QTimer(self)
        self._move_timer.setInterval(12)
        self._move_timer.timeout.connect(self._tick_system_move)
        try:
            self._app.aboutToQuit.connect(self.shutdown)
        except Exception:
            pass

        self._restore_geometry_from_settings()
        self._quick_host.setSource(source_url)
        self.setWindowTitle(self._title)

    def _sync_quick_geometry(self) -> None:
        try:
            guard = self._quick_resize_guard()
            backing_target = self.rect()
            if self._backing.geometry() != backing_target:
                self._backing.setGeometry(backing_target)
            self._backing.lower()
            target = backing_target.adjusted(0, 0, -guard, -guard)
            if self._quick_host.geometry() != target:
                self._quick_host.setGeometry(target)
        except Exception:
            pass

    def _quick_resize_guard(self) -> int:
        if sys.platform != "win32" or not self._native_size_move_active:
            return 0
        return int(self._live_resize_guard_px)

    def _apply_quick_resize_guard(self) -> None:
        try:
            self._sync_quick_geometry()
            self.update()
            self._quick_host.update()
        except Exception:
            pass

    def _request_quick_repaint(self) -> None:
        try:
            self._backing.update()
            self._quick_host.update()
            self.update()
        except Exception:
            pass

    def _initial_shell_background_color(self) -> QColor:
        try:
            mode = str(self._bridge.theme.mode)
        except Exception:
            mode = "dark"
        return QColor("#FFFBFE" if mode == "light" else "#10141C")

    @Slot("QColor")
    def setShellBackgroundColor(self, color) -> None:
        qcolor = QColor(color)
        if not qcolor.isValid():
            return
        if self._shell_background_animation.state() == QPropertyAnimation.State.Running:
            self._shell_background_animation.stop()
        if qcolor == self._shell_background_color:
            return
        self._set_shell_background_color(qcolor)

    @Slot("QColor", "QColor", int)
    def animateShellBackgroundColor(self, from_color, to_color, duration_ms: int) -> None:
        start = QColor(from_color)
        end = QColor(to_color)
        if not start.isValid() or not end.isValid():
            self.setShellBackgroundColor(end if end.isValid() else start)
            return
        if self._shell_background_animation.state() == QPropertyAnimation.State.Running:
            self._shell_background_animation.stop()
        self._set_shell_background_color(start)
        if start == end:
            return
        self._shell_background_animation.setDuration(max(0, int(duration_ms)))
        self._shell_background_animation.setStartValue(start)
        self._shell_background_animation.setEndValue(end)
        self._shell_background_animation.start()

    def _set_shell_background_color(self, qcolor: QColor) -> None:
        if not qcolor.isValid():
            return
        self._shell_background_color = QColor(qcolor)
        try:
            self._quick_host.setClearColor(self._shell_background_color)
            self._quick_host.setPaletteColor(self._shell_background_color)
            self._quick_host.update()
        except Exception:
            pass
        try:
            self._set_widget_palette_color(self, self._shell_background_color)
            self._set_widget_palette_color(self._backing, self._shell_background_color)
        except Exception:
            pass
        try:
            self._backing.update()
            self.update()
        except Exception:
            pass

    def _set_widget_palette_color(self, widget: QWidget, color: QColor) -> None:
        palette = widget.palette()
        palette.setColor(QPalette.ColorRole.Window, color)
        widget.setPalette(palette)

    def paintEvent(self, event):  # noqa: N802
        try:
            painter = QPainter(self)
            painter.fillRect(self.rect(), self._shell_background_color)
            painter.end()
        except Exception:
            pass
        return super().paintEvent(event)

    def _get_animated_shell_background(self) -> QColor:
        return QColor(self._shell_background_color)

    def _set_animated_shell_background(self, color) -> None:
        self._set_shell_background_color(QColor(color))

    animatedShellBackground = Property(QColor, _get_animated_shell_background, _set_animated_shell_background)

    @Slot(bool)
    def setNativeWidgetAgentReady(self, ready: bool) -> None:
        was_ready = self._native_widget_agent_ready
        self._native_widget_agent_ready = bool(ready)
        if self._native_widget_agent_ready and not was_ready:
            self._native_agent_call("setShellBackgroundColor", self._shell_background_color)
            self._native_agent_call("setCornerRadius", self._corner_radius)
            self._apply_windows_chrome()

    @Slot()
    def syncQuickGeometry(self) -> None:
        self._sync_quick_geometry()

    @Slot(bool)
    def setNativeSizeMoveActive(self, active: bool) -> None:
        active = bool(active)
        if self._native_size_move_active == active:
            return
        self._native_size_move_active = active
        self._apply_quick_resize_guard()

    @Slot()
    def handleNativeMoving(self) -> None:
        if self._move_state and bool(self._move_state.get("system_move", False)):
            self._update_snap_preview()
        self._request_quick_repaint()

    @Slot()
    def handleNativeWindowPosChanged(self) -> None:
        self._sync_quick_geometry()
        self._request_quick_repaint()
        self.maximizedChanged.emit()
        self.geometryChanged.emit()

    @Slot()
    def refreshWindowsChrome(self) -> None:
        self._apply_windows_chrome()

    @Slot(bool)
    def setNativeDragRestoreVisual(self, enabled: bool) -> None:
        self._set_native_drag_restore_visual(bool(enabled))

    @Property(bool, notify=maximizedChanged)
    def maximized(self) -> bool:
        return bool(self._is_maximized_state() or self.isFullScreen())

    @Property(bool, notify=geometryChanged)
    def snapped(self) -> bool:
        return bool(self._is_snap_geometry())

    @Property(bool, notify=activeChanged)
    def active(self) -> bool:
        return bool(self.isActiveWindow())

    @Property(bool, notify=alwaysOnTopChanged)
    def alwaysOnTop(self) -> bool:
        return self._always_on_top

    @Property(bool, constant=True)
    def customShadowEnabled(self) -> bool:
        return bool(self._custom_shadow_enabled)

    @Property(bool, constant=True)
    def customChromeEnabled(self) -> bool:
        return bool(self._custom_shadow_enabled)

    @Property(str, constant=True)
    def nativeHwnd(self) -> str:
        try:
            return str(int(self.winId()))
        except Exception:
            return ""

    @Property(int, constant=True)
    def resizeBorder(self) -> int:
        return int(self._resize_border)

    @Property(str, constant=True)
    def windowKey(self) -> str:
        return str(self._window_key)

    @Property(str, constant=True)
    def pageSource(self) -> str:
        return str(self._page_source)

    @Property(str, constant=True)
    def pageTitle(self) -> str:
        return str(self._page_title)

    @Property(bool, constant=True)
    def showPinButton(self) -> bool:
        return bool(self._show_pin_button)

    @Property(bool, constant=True)
    def mainWindow(self) -> bool:
        return bool(self._is_main_window)

    @Property(int, notify=geometryChanged)
    def x(self) -> int:  # for ChildWindow positioning compatibility
        return int(self.geometry().x())

    @Property(int, notify=geometryChanged)
    def y(self) -> int:
        return int(self.geometry().y())

    @Property(int, notify=geometryChanged)
    def width(self) -> int:
        return int(self.geometry().width())

    @Property(int, notify=geometryChanged)
    def height(self) -> int:
        return int(self.geometry().height())

    @Property(int, notify=geometryChanged)
    def shadowX(self) -> int:
        return int(self.geometry().x())

    @Property(int, notify=geometryChanged)
    def shadowY(self) -> int:
        return int(self.geometry().y())

    @Property(int, notify=geometryChanged)
    def shadowWidth(self) -> int:
        return int(self.geometry().width())

    @Property(int, notify=geometryChanged)
    def shadowHeight(self) -> int:
        return int(self.geometry().height())

    def _native_widget_agent(self):
        try:
            root = self._quick_host.rootObject()
            if root is None:
                return None
            agent = root.property("nativeWidgetAgent")
            return agent
        except Exception:
            return None

    def _native_agent_call(self, method: str, *args):
        try:
            agent = self._native_widget_agent()
            if agent is None:
                return None
            fn = getattr(agent, method, None)
            if fn is None:
                return None
            return fn(*args)
        except Exception:
            return None

    def _native_rect_call(self, method: str) -> QRect | None:
        value = self._native_agent_call(method)
        if not isinstance(value, dict):
            return None
        try:
            rect = QRect(
                int(value.get("x", 0)),
                int(value.get("y", 0)),
                int(value.get("width", 0)),
                int(value.get("height", 0)),
            )
            return rect if rect.isValid() else None
        except Exception:
            return None

    @Slot(result=bool)
    def isMaximizedState(self) -> bool:
        agent_value = self._native_agent_call("isMaximizedNative")
        if agent_value is not None:
            return bool(agent_value or self.isFullScreen())
        return bool(self._is_maximized_state() or self.isFullScreen())

    @Slot(result=bool)
    def isSnappedState(self) -> bool:
        return self._snap_geometry_kind() in {"full", "left", "right"}

    @Slot()
    def shutdown(self) -> None:
        self._move_state = None
        self._hide_snap_preview()
        if self._move_timer.isActive():
            self._move_timer.stop()

    @Slot()
    @Slot(float, float)
    def beginSystemMove(self, local_x: float = -1.0, local_y: float = -1.0) -> None:
        if sys.platform != "win32":
            return
        if self._native_widget_agent_ready:
            return
        try:
            self._hide_snap_preview()
            if self.isMaximized() or self.isFullScreen() or self._is_snap_geometry():
                self._begin_manual_restore_move(float(local_x), float(local_y))
                return
            if self._begin_native_caption_move(float(local_x), float(local_y)):
                return
            self._save_normal_geometry()
            geometry = self.geometry()
            self._move_state = {
                "local_x": float(local_x),
                "local_y": float(local_y),
                "width": int(geometry.width()),
                "height": int(geometry.height()),
            }
            self._ensure_move_timer()
        except Exception:
            pass

    @Slot(float, float, float, float, float)
    def setTitleBarHitTestMetrics(self, height: float, left_a: float, right_a: float, left_b: float, right_b: float) -> None:
        regions: list[tuple[int, int]] = []
        for left, right in ((left_a, right_a), (left_b, right_b)):
            try:
                lval = max(0, int(round(float(left))))
                rval = max(0, int(round(float(right))))
            except Exception:
                continue
            if rval > lval + 2:
                regions.append((lval, rval))
        try:
            self._title_bar_height = max(24, min(80, int(round(float(height)))))
        except Exception:
            self._title_bar_height = 36
        self._caption_regions = regions

    @Slot(int)
    def setCornerRadius(self, radius: int) -> None:
        try:
            next_radius = max(0, min(96, int(radius)))
        except Exception:
            next_radius = 0
        if next_radius == self._corner_radius and self._native_widget_agent_ready:
            return
        self._corner_radius = next_radius
        self._native_agent_call("setCornerRadius", next_radius)
        self._apply_widget_mask()

    @Slot()
    def updateSystemMove(self) -> None:
        if sys.platform == "win32" and self._native_widget_agent_ready:
            return
        if self._move_state and bool(self._move_state.get("system_move", False)):
            return
        self._apply_system_move()

    def _apply_system_move(self) -> None:
        state = self._move_state
        if not state:
            return
        cursor = QCursor.pos()
        if bool(state.get("manual_restore_pending", False)):
            dx = abs(int(cursor.x()) - int(state.get("start_x", cursor.x())))
            dy = abs(int(cursor.y()) - int(state.get("start_y", cursor.y())))
            if dx + dy < 4:
                return
            self._start_manual_restore_drag(state, cursor)
            return
        restore = QRect(state.get("restore_geometry", QRect()))
        width = int(restore.width() if restore.isValid() else state["width"])
        height = int(restore.height() if restore.isValid() else state["height"])
        new_x = int(cursor.x() - float(state["local_x"]))
        new_y = int(cursor.y() - float(state["local_y"]))
        if bool(state.get("manual_restore_started", False)):
            self._apply_manual_restore_locked_geometry(state, new_x, new_y, width, height)
            self._update_snap_preview()
            return
        current = self.geometry()
        if new_x != current.x() or new_y != current.y() or width != current.width() or height != current.height():
            target = QRect(new_x, new_y, width, height)
            self._apply_move_geometry(target, bool(state.get("manual_restore_started", False)))
            if bool(state.get("manual_restore_started", False)):
                state["last_geometry"] = QRect(new_x, new_y, width, height)
            else:
                self._normal_geometry = QRect(new_x, new_y, width, height)
            self.geometryChanged.emit()
        self._update_snap_preview()

    def _apply_manual_restore_locked_geometry(self, state: dict, x: int, y: int, width: int, height: int) -> None:
        target = QRect(int(x), int(y), int(width), int(height))
        current = QRect(self.geometry())
        size_drift = abs(int(current.width()) - int(width)) > 1 or abs(int(current.height()) - int(height)) > 1
        position_drift = int(current.x()) != int(x) or int(current.y()) != int(y)
        if not size_drift and not position_drift:
            return
        try:
            self.setGeometry(target)
            current = QRect(self.geometry())
            if (
                abs(int(current.x()) - int(target.x())) <= 1
                and abs(int(current.y()) - int(target.y())) <= 1
                and abs(int(current.width()) - int(target.width())) <= 1
                and abs(int(current.height()) - int(target.height())) <= 1
            ):
                state["last_geometry"] = QRect(target)
                self.geometryChanged.emit()
                return
        except Exception:
            pass
        try:
            try:
                if self._left_button_down():
                    self._native_agent_call("setMouseCaptureNative", True)
            except Exception:
                pass
            if size_drift:
                if self._native_agent_call("setWindowGeometryNative", int(x), int(y), int(width), int(height), True, True) is not True:
                    raise RuntimeError("native geometry failed")
            else:
                if self._native_agent_call("setWindowGeometryNative", int(x), int(y), 0, 0, False, True) is not True:
                    raise RuntimeError("native move failed")
            state["last_geometry"] = QRect(target)
            self.geometryChanged.emit()
        except Exception:
            self.setGeometry(target)
            state["last_geometry"] = QRect(target)
            self.geometryChanged.emit()

    def _apply_move_geometry(self, target: QRect, force_native: bool = False) -> None:
        if sys.platform == "win32" and force_native:
            try:
                if self._native_agent_call(
                    "setWindowGeometryNative",
                    int(target.x()),
                    int(target.y()),
                    int(target.width()),
                    int(target.height()),
                    True,
                    False,
                ) is True:
                    return
            except Exception:
                pass
        self.setGeometry(target)

    def _ensure_move_timer(self) -> None:
        if not self._move_timer.isActive():
            self._move_timer.start()

    def _tick_system_move(self) -> None:
        if not self._move_state:
            self._move_timer.stop()
            return
        if bool(self._move_state.get("system_move", False)):
            self._update_snap_preview()
            if not self._left_button_down():
                self._finish_native_caption_move()
            return
        if not self._left_button_down():
            self.endSystemMove()
            return
        self._apply_system_move()

    def _left_button_down(self) -> bool:
        try:
            if bool(QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton):
                return True
        except Exception:
            pass
        if sys.platform == "win32":
            try:
                return bool(user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
            except Exception:
                pass
        return False

    @Slot()
    def endSystemMove(self) -> None:
        if sys.platform == "win32" and self._native_widget_agent_ready and not self._move_state:
            return
        state = self._move_state
        self._move_state = None
        if self._move_timer.isActive():
            self._move_timer.stop()
        if not state:
            return
        if bool(state.get("system_move", False)):
            self._record_native_caption_result(state)
            return
        if sys.platform == "win32":
            try:
                self._native_agent_call("setMouseCaptureNative", False)
            except Exception:
                pass
        if bool(state.get("manual_restore_pending", False)) and not bool(state.get("manual_restore_started", False)):
            self._hide_snap_preview()
            self._set_native_drag_restore_visual(False)
            self.maximizedChanged.emit()
            self.geometryChanged.emit()
            return
        target = self._snap_target_for_cursor()
        if target is not None:
            snap_rect, snap_type = target
            if bool(state.get("manual_restore_started", False)):
                restored = QRect(state.get("last_geometry", state.get("restore_geometry", self.geometry())))
                self._normal_geometry = QRect(restored)
                self._remember_normal_frame_geometry(restored)
                self._save_geometry_to_settings()
            else:
                self._store_normal_geometry(QRect(self.geometry()))
            if snap_type == "top":
                super().showMaximized()
                self.maximizedChanged.emit()
            else:
                self.setGeometry(snap_rect)
            self._hide_snap_preview()
        elif self._should_store_as_normal_geometry():
            self._hide_snap_preview()
            if bool(state.get("manual_restore_started", False)):
                restored = QRect(state.get("last_geometry", self.geometry()))
                self._normal_geometry = QRect(restored)
                self._remember_normal_frame_geometry(restored)
                self._save_geometry_to_settings()
            else:
                self._store_normal_geometry(QRect(self.geometry()))
        else:
            self._hide_snap_preview()
        self._set_native_drag_restore_visual(False)
        self.geometryChanged.emit()

    @Slot()
    def toggleMaximized(self) -> None:
        native_maximized = None
        if sys.platform == "win32":
            native_maximized = self._native_agent_call("isMaximizedNative")
            if native_maximized is False:
                self._save_normal_geometry()
        if sys.platform == "win32" and self._native_agent_call("toggleMaximizedNative") is True:
            pass
        elif sys.platform == "win32" and self._send_native_maximize_command():
            pass
        elif self.isMaximized():
            self.showNormal()
        else:
            self._save_normal_geometry()
            self.showMaximized()
        self.maximizedChanged.emit()
        self.geometryChanged.emit()

    @Slot()
    def showMinimizedNative(self) -> None:
        if sys.platform == "win32" and self._native_agent_call("showMinimizedNative") is True:
            return
        self.showMinimized()

    @Slot(float, float, float, float)
    def expandForInlineWorkspace(self, left: float, top: float, right: float, bottom: float) -> None:
        if self.isMaximized() or self.isFullScreen() or self._is_snap_geometry():
            return
        try:
            grow_left = max(0, min(160, int(round(float(left)))))
            grow_top = max(0, min(160, int(round(float(top)))))
            grow_right = max(0, min(160, int(round(float(right)))))
            grow_bottom = max(0, min(160, int(round(float(bottom)))))
        except Exception:
            return
        if grow_left + grow_top + grow_right + grow_bottom <= 0:
            return
        grow_left = min(12, max(4, grow_left)) if grow_left > 0 else 0
        grow_top = min(12, max(4, grow_top)) if grow_top > 0 else 0
        grow_right = min(12, max(4, grow_right)) if grow_right > 0 else 0
        grow_bottom = min(12, max(4, grow_bottom)) if grow_bottom > 0 else 0
        current = QRect(self.geometry())
        target = QRect(
            current.x() - grow_left,
            current.y() - grow_top,
            current.width() + grow_left + grow_right,
            current.height() + grow_top + grow_bottom,
        )
        area = self._screen_available_geometry()
        if area is not None and area.isValid():
            if target.x() < area.x():
                target.setX(area.x())
            if target.y() < area.y():
                target.setY(area.y())
            if target.right() > area.right():
                target.setRight(area.right())
            if target.bottom() > area.bottom():
                target.setBottom(area.bottom())
        target.setWidth(max(self.minimumWidth(), target.width()))
        target.setHeight(max(self.minimumHeight(), target.height()))
        if target == current:
            return
        self.setGeometry(target)
        self._store_normal_geometry(QRect(self.geometry()))
        self.geometryChanged.emit()

    @Slot()
    def closeWindow(self) -> None:
        if not self._is_main_window:
            if self._closing_from_dialog_service:
                self.close()
                return
            try:
                self._bridge.dialogs.closeChildWindow(self)
                return
            except Exception:
                pass
            self.close()
            return
        if self._close_to_tray:
            try:
                if self._bridge.tray.handleClosing(self):
                    return
            except Exception:
                pass
        if self._is_main_window:
            try:
                self._bridge.dialogs.shutdown()
            except Exception:
                pass
            if self._use_windows_fast_exit():
                write_runtime_log("NativeFramelessHost.closeWindow using AppBridge fast exit")
                self._bridge.exitApplication()
                return
        self.close()

    def markDialogServiceClosing(self) -> None:
        self._closing_from_dialog_service = True

    def _apply_hwnd_topmost(self, hwnd: int, enabled: bool, activate: bool = False) -> None:
        if sys.platform != "win32" or not hwnd:
            return
        try:
            hwnd_p = wintypes.HWND(int(hwnd))
            if not user32.IsWindow(hwnd_p):
                return
            HWND_TOPMOST = -1
            HWND_NOTOPMOST = -2
            flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOOWNERZORDER
            if not (enabled and activate):
                flags |= SWP_NOACTIVATE
            user32.SetWindowPos(hwnd_p, wintypes.HWND(HWND_TOPMOST if enabled else HWND_NOTOPMOST), 0, 0, 0, 0, flags)
            if enabled and activate:
                try:
                    user32.BringWindowToTop(hwnd_p)
                except Exception:
                    pass
        except Exception:
            pass

    @Slot(bool)
    def setAlwaysOnTop(self, enabled: bool) -> None:
        enabled = bool(enabled)
        changed = enabled != self._always_on_top
        self._always_on_top = enabled
        if sys.platform == "win32":
            try:
                if self._native_agent_call("setTopMostNative", enabled, enabled) is True:
                    QTimer.singleShot(0, lambda enabled=enabled: self._native_agent_call("setTopMostNative", enabled, False))
                    QTimer.singleShot(80, lambda enabled=enabled: self._native_agent_call("setTopMostNative", enabled, False))
                    QTimer.singleShot(180, lambda enabled=enabled: self._native_agent_call("setTopMostNative", enabled, False))
                else:
                    hwnd_value = int(self.winId())
                    self._apply_hwnd_topmost(hwnd_value, enabled, activate=enabled)
                    QTimer.singleShot(0, lambda hwnd_value=hwnd_value, enabled=enabled: self._apply_hwnd_topmost(hwnd_value, enabled, activate=False))
                    QTimer.singleShot(80, lambda hwnd_value=hwnd_value, enabled=enabled: self._apply_hwnd_topmost(hwnd_value, enabled, activate=False))
                    QTimer.singleShot(180, lambda hwnd_value=hwnd_value, enabled=enabled: self._apply_hwnd_topmost(hwnd_value, enabled, activate=False))
            except Exception:
                pass
        else:
            flags = self.windowFlags()
            if enabled:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowType.WindowStaysOnTopHint
            was_visible = self.isVisible()
            self.setWindowFlags(flags)
            if was_visible:
                self.show()
                self.raise_()
                self.activateWindow()
        if changed:
            self.alwaysOnTopChanged.emit(enabled)

    @Slot()
    def activateHost(self) -> None:
        if sys.platform == "win32" and self._native_agent_call("activateNative") is True:
            return
        self.raise_()
        self.activateWindow()

    @Slot(str)
    def showToast(self, message: str) -> None:
        self.toastRequested.emit(str(message))

    @Slot(str, int, int)
    def changeThemeWithRipple(self, next_mode: str, x: int, y: int) -> None:
        try:
            self._bridge.theme.setRippleOrigin(int(x), int(y))
            self._bridge.theme.setMode(str(next_mode))
        except Exception:
            pass

    def showNormal(self):  # noqa: N802 - Qt API compatibility
        if sys.platform == "win32" and self.isVisible() and self._native_agent_call("showNormalNative") is True:
            pass
        elif sys.platform == "win32" and self.isVisible():
            try:
                user32.SendMessageW(wintypes.HWND(int(self.winId())), WM_SYSCOMMAND, SC_RESTORE, 0)
            except Exception:
                super().showNormal()
        else:
            super().showNormal()
        self.maximizedChanged.emit()
        self.geometryChanged.emit()

    def showMaximized(self):  # noqa: N802
        self._save_normal_geometry(force=True)
        if sys.platform == "win32" and self._native_agent_call("showMaximizedNative") is True:
            pass
        elif sys.platform == "win32":
            try:
                user32.SendMessageW(wintypes.HWND(int(self.winId())), WM_SYSCOMMAND, SC_MAXIMIZE, 0)
            except Exception:
                super().showMaximized()
        else:
            super().showMaximized()
        self.maximizedChanged.emit()
        self.geometryChanged.emit()

    def moveEvent(self, event):  # noqa: N802
        if self._should_store_as_normal_geometry():
            self._store_normal_geometry(QRect(self.geometry()))
        result = super().moveEvent(event)
        self._request_quick_repaint()
        self.maximizedChanged.emit()
        self.geometryChanged.emit()
        return result

    def resizeEvent(self, event):  # noqa: N802
        if self._should_store_as_normal_geometry():
            self._store_normal_geometry(QRect(self.geometry()))
        result = super().resizeEvent(event)
        self._sync_quick_geometry()
        self._apply_widget_mask()
        self.maximizedChanged.emit()
        self.geometryChanged.emit()
        return result

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        self._apply_windows_chrome()
        self._sync_quick_geometry()
        QTimer.singleShot(0, self._sync_quick_geometry)
        self.maximizedChanged.emit()
        self.activeChanged.emit()

    def closeEvent(self, event):  # noqa: N802
        if self._is_main_window:
            if self._close_to_tray:
                try:
                    if self._bridge.tray.handleClosing(self):
                        write_runtime_log("NativeFramelessHost.closeEvent handled by tray")
                        event.ignore()
                        return
                except Exception:
                    pass
            if self._use_windows_fast_exit():
                write_runtime_log("NativeFramelessHost.closeEvent using AppBridge fast exit")
                event.ignore()
                try:
                    self._bridge.exitApplication()
                except Exception:
                    pass
                return
        self._save_normal_geometry()
        self._save_geometry_to_settings()
        if self._is_main_window:
            try:
                self._bridge.dialogs.shutdown()
            except Exception:
                pass
        else:
            try:
                root = self._quick_host.rootObject()
                if root is not None and hasattr(root, "cleanupExternalShadow"):
                    root.cleanupExternalShadow()
            except Exception:
                pass
        result = super().closeEvent(event)
        if event.isAccepted() and self._quit_on_close:
            QTimer.singleShot(0, self._app.quit)
        return result

    def _use_windows_fast_exit(self) -> bool:
        return (
            sys.platform == "win32"
            and os.environ.get("QROUNDEDFRAME_DISABLE_FAST_EXIT", "").strip().lower() not in {"1", "true", "yes"}
        )

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._apply_windows_chrome()
        self._apply_widget_mask()
        self._sync_quick_geometry()
        self.maximizedChanged.emit()
        self.activeChanged.emit()
        self.geometryChanged.emit()
        self.nativeShown.emit()

    def nativeEvent(self, event_type, message):  # noqa: N802
        if sys.platform != "win32" or MSG is None:
            return False, 0
        if self._native_widget_agent_ready:
            return False, 0
        try:
            msg = MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message == WM_MOVING:
            if self._move_state and bool(self._move_state.get("system_move", False)):
                self._update_snap_preview()
            self._request_quick_repaint()
            return False, 0
        if msg.message == WM_WINDOWPOSCHANGED:
            self._sync_quick_geometry()
            self._request_quick_repaint()
            self.maximizedChanged.emit()
            self.geometryChanged.emit()
            return False, 0
        return False, 0

    def _shadow_inset(self) -> int:
        if not self._custom_shadow_enabled:
            return 0
        inset = 0
        try:
            root = self._quick_host.rootObject()
            if root is not None:
                if bool(root.property("nativeExternalShadow")):
                    self._last_shadow_inset = 0
                    return 0
                inset = max(0, min(96, int(root.property("shadowVisualInset") or 0)))
        except Exception:
            pass
        if inset > 0:
            self._last_shadow_inset = inset
        if self._is_maximized_state() or self.isFullScreen() or self._is_snap_geometry():
            return 0
        return inset

    def _normal_shadow_inset(self) -> int:
        if not self._custom_shadow_enabled:
            return 0
        try:
            root = self._quick_host.rootObject()
            if root is not None:
                if bool(root.property("nativeExternalShadow")):
                    self._last_shadow_inset = 0
                    return 0
                inset = max(0, min(96, int(root.property("shadowVisualInset") or 0)))
                if inset > 0:
                    self._last_shadow_inset = inset
                    return inset
                return 0
        except Exception:
            pass
        if self._native_widget_agent_ready:
            return 0
        if self._last_shadow_inset > 0:
            return int(self._last_shadow_inset)
        return 0

    def _is_maximized_state(self) -> bool:
        if sys.platform == "win32":
            try:
                return bool(user32.IsZoomed(wintypes.HWND(int(self.winId()))))
            except Exception:
                pass
        return bool(self.isMaximized())

    def _is_special_restore_state(self) -> bool:
        return bool(self._is_maximized_state() or self.isFullScreen() or self._is_snap_geometry())

    def _send_native_maximize_command(self) -> bool:
        try:
            hwnd = wintypes.HWND(int(self.winId()))
            if not hwnd:
                return False
            if self._is_maximized_state():
                user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_RESTORE, 0)
            else:
                self._save_normal_geometry()
                user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_MAXIMIZE, 0)
            return True
        except Exception:
            return False

    def _apply_windows_chrome(self) -> None:
        if sys.platform != "win32":
            return
        if self._native_agent_call("applyWindowsChromeNative") is True:
            self._apply_widget_mask()
            return
        try:
            hwnd = wintypes.HWND(int(self.winId()))
            try:
                style = user32.GetWindowLongW(hwnd, GWL_STYLE)
                style |= WS_THICKFRAME | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
                user32.SetWindowLongW(hwnd, GWL_STYLE, style)
                user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
            except Exception:
                pass
            pref = ctypes.c_int(DWMWCP_DEFAULT if is_windows_11_or_newer() else DWMWCP_ROUND)
            dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(pref), ctypes.sizeof(pref))
            try:
                # Keep DWM non-client rendering enabled.  Disabling it makes
                # Win10 draw the classic caption/buttons behind our QML chrome
                # while resizing.
                policy = ctypes.c_int(DWMNCRP_ENABLED)
                dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_NCRENDERING_POLICY, ctypes.byref(policy), ctypes.sizeof(policy))
            except Exception:
                pass
            try:
                border_color = ctypes.c_uint(DWMWA_COLOR_NONE)
                dwmapi.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR, ctypes.byref(border_color), ctypes.sizeof(border_color))
            except Exception:
                pass
            try:
                margins = MARGINS(0, 0, 0, 0) if self._custom_shadow_enabled else MARGINS(1, 1, 1, 1)
                dwmapi.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
            except Exception:
                pass
        except Exception:
            pass
        self._apply_widget_mask()

    def _apply_widget_mask(self) -> None:
        try:
            if self._native_widget_agent_ready:
                self.clearMask()
                return
            if self.isMaximized() or self.isFullScreen() or self._is_snap_geometry() or self._corner_radius <= 0:
                self.clearMask()
                return
            rect = self.rect()
            if rect.width() <= 0 or rect.height() <= 0:
                return
            radius = max(1.0, float(self._corner_radius))
            path = QPainterPath()
            path.addRoundedRect(rect, radius, radius)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))
        except Exception:
            pass

    def _restore_geometry_from_settings(self) -> None:
        settings = self._bridge.settings
        saved = settings.value_py(f"{self._settings_key}/normalGeometry", None)
        if isinstance(saved, dict):
            try:
                rect = QRect(
                    int(saved.get("x", self._default_geometry.x())),
                    int(saved.get("y", self._default_geometry.y())),
                    int(saved.get("w", self._default_geometry.width())),
                    int(saved.get("h", self._default_geometry.height())),
                )
                if self._normal_geometry_candidate_is_usable(rect):
                    self._normal_geometry = QRect(rect)
                    self._normal_frame_geometry = QRect(rect)
                    self.setGeometry(rect)
                    return
            except Exception:
                pass
        rect = self._repair_normal_geometry()
        self._normal_geometry = QRect(rect)
        self._normal_frame_geometry = QRect(rect)
        self.setGeometry(rect)
        self._save_geometry_to_settings()

    def _screen_available_geometry(self):
        try:
            screen = self.screen() or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            return screen.availableGeometry() if screen is not None else None
        except Exception:
            return None

    def _is_snap_geometry(self, rect: QRect | None = None) -> bool:
        return bool(self._snap_geometry_kind(rect))

    def _snap_geometry_kind(self, rect: QRect | None = None) -> str:
        rect = QRect(rect or self.geometry())
        area = self._screen_available_geometry()
        if area is None:
            return ""
        tol = 8
        same_height = abs(rect.y() - area.y()) <= tol and abs(rect.height() - area.height()) <= tol
        left_half = abs(rect.x() - area.x()) <= tol and abs(rect.width() - area.width() / 2) <= max(tol, area.width() * 0.04)
        right_half = abs(rect.right() - area.right()) <= tol and abs(rect.width() - area.width() / 2) <= max(tol, area.width() * 0.04)
        near_full = abs(rect.x() - area.x()) <= tol and abs(rect.y() - area.y()) <= tol and abs(rect.width() - area.width()) <= tol and abs(rect.height() - area.height()) <= tol
        vertical_fill = same_height and rect.width() < area.width() - max(tol * 2, 80)
        if near_full:
            return "full"
        if same_height and left_half:
            return "left"
        if same_height and right_half:
            return "right"
        if vertical_fill:
            return "vertical"
        return ""

    def _normal_geometry_candidate_is_usable(self, rect: QRect) -> bool:
        try:
            geom = QRect(rect)
            if not geom.isValid():
                return False
            if geom.width() < self.minimumWidth() or geom.height() < self.minimumHeight():
                return False
            if self._normal_geometry_looks_shadow_shrunk(geom):
                return False
            if self._normal_geometry_looks_bad_restore_size(geom):
                return False
            if self._snap_geometry_kind(geom):
                return False
            area = self._screen_available_geometry()
            if area is not None:
                if geom.width() >= area.width() - 16 and geom.height() >= area.height() - 16:
                    return False
            return True
        except Exception:
            return False

    def _normal_geometry_looks_bad_restore_size(self, rect: QRect) -> bool:
        try:
            area = self._screen_available_geometry()
            if area is None:
                return False
            geom = QRect(rect)
            ratio = float(geom.width()) / float(max(1, geom.height()))
            tall_narrow = ratio < 1.08 and geom.height() > float(area.height()) * 0.58
            half_width_tall = geom.width() <= float(area.width()) * 0.56 and geom.height() > float(area.height()) * 0.66
            return bool(tall_narrow or half_width_tall)
        except Exception:
            return False

    def _repair_special_restore_normal_geometry(self, reference: QRect | None = None) -> QRect:
        area = self._screen_available_geometry()
        min_w = self.minimumWidth()
        min_h = self.minimumHeight()
        inset = int(self._normal_shadow_inset())
        if area is None:
            return QRect(160, 90, max(1080, min_w + 220), max(700, min_h + 160))
        width = min(max(1080, min_w + 220), max(min_w, int(area.width()) - inset * 2))
        height = min(max(700, min_h + 160), max(min_h, int(area.height()) - inset * 2))
        x = int(area.x() + (area.width() - width) / 2)
        y = int(area.y() + (area.height() - height) / 2)
        try:
            ref = QRect(reference) if reference is not None else QRect()
            if ref.isValid():
                x = max(int(area.x() - inset), min(int(ref.x()), int(area.right() - width + inset + 1)))
                y = max(int(area.y() - inset), min(int(ref.y()), int(area.bottom() - height + inset + 1)))
        except Exception:
            pass
        return QRect(x, y, width, height)

    def _normal_geometry_looks_shadow_shrunk(self, rect: QRect) -> bool:
        try:
            inset = int(self._normal_shadow_inset())
            if inset <= 0:
                return False
            return (
                int(rect.width()) <= int(self.minimumWidth()) + inset * 2 + 8
                or int(rect.height()) <= int(self.minimumHeight()) + inset * 2 + 8
            )
        except Exception:
            return False

    def _repair_normal_geometry(self, reference: QRect | None = None) -> QRect:
        area = self._screen_available_geometry()
        inset = int(self._normal_shadow_inset())
        min_w = self.minimumWidth()
        min_h = self.minimumHeight()
        if area is None:
            return QRect(160, 90, max(1280, min_w + inset * 2), max(780, min_h + inset * 2))
        width = min(max(1280, int(area.width() * 0.70), min_w + inset * 2 + 160), max(min_w, int(area.width()) - inset * 2))
        height = min(max(780, int(area.height() * 0.76), min_h + inset * 2 + 120), max(min_h, int(area.height()) - inset * 2))
        x = int(area.x() + (area.width() - width) / 2)
        y = int(area.y() + (area.height() - height) / 2)
        try:
            ref = QRect(reference) if reference is not None else QRect()
            if ref.isValid():
                x = max(int(area.x() - inset), min(int(ref.x()), int(area.right() - width + inset + 1)))
                y = max(int(area.y() - inset), min(int(ref.y()), int(area.bottom() - height + inset + 1)))
        except Exception:
            pass
        return QRect(x, y, width, height)

    def _saved_normal_geometry(self) -> QRect | None:
        try:
            saved = self._bridge.settings.value_py(f"{self._settings_key}/normalGeometry", None)
            if not isinstance(saved, dict):
                return None
            rect = QRect(
                int(saved.get("x", self._default_geometry.x())),
                int(saved.get("y", self._default_geometry.y())),
                int(saved.get("w", self._default_geometry.width())),
                int(saved.get("h", self._default_geometry.height())),
            )
            return rect if rect.isValid() else None
        except Exception:
            return None

    def _windows_restore_bounds(self) -> QRect | None:
        if sys.platform != "win32":
            return None
        native = self._native_rect_call("restoreBoundsNative")
        if native is not None:
            return native
        try:
            placement = WINDOWPLACEMENT()
            placement.length = ctypes.sizeof(WINDOWPLACEMENT)
            hwnd = wintypes.HWND(int(self.winId()))
            if not user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
                return None
            rect = placement.rcNormalPosition
            geom = QRect(
                int(rect.left),
                int(rect.top),
                int(rect.right - rect.left),
                int(rect.bottom - rect.top),
            )
            return geom if geom.isValid() else None
        except Exception:
            return None

    def _best_special_restore_normal_geometry(self) -> QRect:
        fallback: QRect | None = None
        for candidate in (
            self._normal_geometry,
            self._saved_normal_geometry(),
            self._windows_restore_bounds(),
            QRect(self.geometry()),
        ):
            if candidate is None:
                continue
            geom = QRect(candidate)
            if fallback is None and geom.isValid():
                fallback = QRect(geom)
            if self._normal_geometry_candidate_is_usable(geom):
                return QRect(geom)
        return self._repair_special_restore_normal_geometry(fallback or QRect(self.geometry()))

    def _should_store_as_normal_geometry(self) -> bool:
        if self._move_state is not None:
            return False
        return not self.isMaximized() and not self.isFullScreen() and not self._is_snap_geometry()

    def _save_normal_geometry(self, force: bool = False) -> None:
        if force or self._should_store_as_normal_geometry():
            g = QRect(self.geometry())
            if self._normal_geometry_candidate_is_usable(g):
                self._store_normal_geometry(g)

    def _store_normal_geometry(self, candidate: QRect) -> None:
        if not self._normal_geometry_candidate_is_usable(candidate):
            if self._normal_geometry_candidate_is_usable(self._normal_geometry):
                return
            geom = self._repair_normal_geometry(candidate)
            self._normal_geometry = QRect(geom)
            self._remember_normal_frame_geometry(geom)
            return
        geom = self._coalesced_normal_geometry(candidate)
        self._normal_geometry = QRect(geom)
        self._remember_normal_frame_geometry(geom)

    def _coalesced_normal_geometry(self, candidate: QRect) -> QRect:
        previous = self._normal_geometry
        if not previous.isValid():
            return QRect(candidate)
        try:
            dw = abs(int(candidate.width()) - int(previous.width()))
            dh = abs(int(candidate.height()) - int(previous.height()))
            if dw <= 32 and dh <= 32:
                return QRect(int(candidate.x()), int(candidate.y()), int(previous.width()), int(previous.height()))
        except Exception:
            pass
        return QRect(candidate)

    def _current_frame_geometry(self) -> QRect:
        if sys.platform == "win32":
            native = self._native_rect_call("windowFrameGeometryNative")
            if native is not None:
                return native
            try:
                rect = wintypes.RECT()
                hwnd = wintypes.HWND(int(self.winId()))
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return QRect(
                        int(rect.left),
                        int(rect.top),
                        int(rect.right - rect.left),
                        int(rect.bottom - rect.top),
                    )
            except Exception:
                pass
        try:
            frame = self.frameGeometry()
            if frame.isValid():
                return QRect(frame)
        except Exception:
            pass
        return QRect(self.geometry())

    def _remember_normal_frame_geometry(self, client_geom: QRect) -> None:
        frame = self._current_frame_geometry()
        if not frame.isValid():
            return
        try:
            dw = int(frame.width()) - int(client_geom.width())
            dh = int(frame.height()) - int(client_geom.height())
            if 0 <= dw <= 96 and 0 <= dh <= 96:
                self._normal_frame_geometry = QRect(frame)
        except Exception:
            pass

    def _frame_geometry_for_client(self, client_geom: QRect, reference_client: QRect | None = None) -> QRect:
        if sys.platform == "win32":
            try:
                return self._native_outer_rect_for_client(wintypes.HWND(int(self.winId())), client_geom)
            except Exception:
                pass
        reference = QRect(reference_client or self._normal_geometry)
        frame = QRect(self._normal_frame_geometry)
        if frame.isValid() and reference.isValid():
            try:
                dx = int(frame.x()) - int(reference.x())
                dy = int(frame.y()) - int(reference.y())
                dw = int(frame.width()) - int(reference.width())
                dh = int(frame.height()) - int(reference.height())
                if abs(dx) <= 96 and abs(dy) <= 96 and 0 <= dw <= 128 and 0 <= dh <= 128:
                    return QRect(
                        int(client_geom.x()) + dx,
                        int(client_geom.y()) + dy,
                        int(client_geom.width()) + dw,
                        int(client_geom.height()) + dh,
                    )
            except Exception:
                pass
        return QRect(client_geom)

    def _native_outer_rect_for_client(self, hwnd: wintypes.HWND, client_geom: QRect) -> QRect:
        # WM_NCCALCSIZE collapses the native frame into the client area, so the
        # visible window bounds already match client_geom. Expanding with
        # AdjustWindowRectEx would poison WINDOWPLACEMENT and make every native
        # maximize/snap restore save a slightly smaller normal size.
        return QRect(client_geom)

    def _set_restore_bounds_for_client_geometry(self, hwnd: wintypes.HWND, client_geom: QRect, reference_client: QRect | None = None) -> QRect:
        outer = self._frame_geometry_for_client(client_geom, reference_client)
        if self._native_agent_call(
            "setRestoreBoundsNative",
            int(outer.x()),
            int(outer.y()),
            int(outer.width()),
            int(outer.height()),
        ) is True:
            return outer
        try:
            placement = WINDOWPLACEMENT()
            placement.length = ctypes.sizeof(WINDOWPLACEMENT)
            if user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
                placement.rcNormalPosition.left = int(outer.x())
                placement.rcNormalPosition.top = int(outer.y())
                placement.rcNormalPosition.right = int(outer.x() + outer.width())
                placement.rcNormalPosition.bottom = int(outer.y() + outer.height())
                user32.SetWindowPlacement(hwnd, ctypes.byref(placement))
        except Exception:
            pass
        return outer

    def _force_windows_normal_geometry(self, client_geom: QRect, reference_client: QRect | None = None) -> QRect:
        geom = QRect(client_geom)
        if sys.platform != "win32":
            try:
                super().showNormal()
                self.setGeometry(geom)
            except Exception:
                pass
            return geom
        hwnd = wintypes.HWND(int(self.winId()))
        outer = self._frame_geometry_for_client(geom, reference_client)
        applied = QRect(geom)
        try:
            if self._native_agent_call(
                "forceNormalGeometryNative",
                int(outer.x()),
                int(outer.y()),
                int(outer.width()),
                int(outer.height()),
            ) is not True:
                placement = WINDOWPLACEMENT()
                placement.length = ctypes.sizeof(WINDOWPLACEMENT)
                if user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
                    placement.flags = 0
                    placement.showCmd = SW_SHOWNORMAL
                    placement.rcNormalPosition.left = int(outer.x())
                    placement.rcNormalPosition.top = int(outer.y())
                    placement.rcNormalPosition.right = int(outer.x() + outer.width())
                    placement.rcNormalPosition.bottom = int(outer.y() + outer.height())
                    user32.SetWindowPlacement(hwnd, ctypes.byref(placement))
                user32.ShowWindow(hwnd, SW_RESTORE)
                user32.SetWindowPos(
                    hwnd,
                    None,
                    int(outer.x()),
                    int(outer.y()),
                    int(outer.width()),
                    int(outer.height()),
                    SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_FRAMECHANGED,
                )
            actual = self._current_frame_geometry()
            if (
                actual.isValid()
                and abs(int(actual.width()) - int(geom.width())) <= 4
                and abs(int(actual.height()) - int(geom.height())) <= 4
            ):
                applied = QRect(actual)
        except Exception:
            try:
                super().showNormal()
                self.setGeometry(geom)
            except Exception:
                pass
        return applied

    def _set_native_drag_restore_visual(self, enabled: bool) -> None:
        try:
            root = self._quick_host.rootObject()
            if root is not None:
                root.setProperty("nativeDragRestoreVisual", bool(enabled) and bool(self._custom_shadow_enabled))
        except Exception:
            pass

    def _restore_drag_anchor(self, normal: QRect, local_x: float = -1.0, local_y: float = -1.0, current_content_width: float | None = None) -> tuple[float, float]:
        normal_inset = int(self._normal_shadow_inset())
        if current_content_width is None:
            current_inset = int(self._shadow_inset())
            current_content_width = float((self._quick_host.width() or self.geometry().width()) - current_inset * 2)
        current_width = max(1.0, float(current_content_width))
        normal_width = max(1.0, float(int(normal.width()) - normal_inset * 2))
        ratio_x = 0.5
        if local_x is not None and local_x >= 0:
            ratio_x = max(0.0, min(1.0, float(local_x) / current_width))
        title_y = self._caption_restore_anchor_y(local_y)
        return (float(normal_inset) + normal_width * ratio_x, float(normal_inset) + float(title_y))

    def _restore_drag_target(self, normal: QRect, local_x: float = -1.0, local_y: float = -1.0, current_content_width: float | None = None) -> QRect:
        cursor = QCursor.pos()
        anchor_x, anchor_y = self._restore_drag_anchor(normal, local_x, local_y, current_content_width)
        return QRect(
            int(cursor.x() - anchor_x),
            int(cursor.y() - anchor_y),
            int(normal.width()),
            int(normal.height()),
        )

    def _caption_restore_anchor_y(self, local_y: float = -1.0) -> float:
        try:
            title_height = max(24, min(96, int(self._title_bar_height or 38)))
        except Exception:
            title_height = 38
        try:
            y = float(local_y)
        except Exception:
            y = 16.0
        return max(6.0, min(y, float(max(6, title_height - 1))))

    def _begin_native_caption_move(self, local_x: float = -1.0, local_y: float = -1.0) -> bool:
        if sys.platform != "win32":
            return False
        try:
            hwnd_value = int(self.winId())
        except Exception:
            return False
        if not hwnd_value:
            return False
        normal = QRect(self._normal_geometry)
        if not normal.isValid() or normal.width() < self.minimumWidth() or normal.height() < self.minimumHeight():
            normal = QRect(160, 90, 1080, 700)

        special = bool(self._is_special_restore_state())
        if special:
            return False
        restore_geometry = QRect(normal)
        self._save_normal_geometry()
        normal = QRect(self._normal_geometry)
        restore_geometry = QRect(normal)

        self._move_state = {
            "system_move": True,
            "normal_geometry": QRect(normal),
            "restore_geometry": QRect(restore_geometry),
            "started_special": special,
        }
        self._ensure_move_timer()
        try:
            if self._native_agent_call("beginCaptionMoveNative") is not True:
                hwnd = wintypes.HWND(hwnd_value)
                user32.ReleaseCapture()
                user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_MOVE | HTCAPTION, 0)
        except Exception:
            self._move_state = None
            self._stop_move_timer()
            return False
        if self._move_state and not self._left_button_down():
            self._finish_native_caption_move()
        return True

    def _finish_native_caption_move(self) -> None:
        state = self._move_state
        self._move_state = None
        self._stop_move_timer()
        if not state:
            return
        self._record_native_caption_result(state)
        self._set_native_drag_restore_visual(False)
        self._hide_snap_preview()

    def _stop_move_timer(self) -> None:
        if self._move_timer.isActive():
            self._move_timer.stop()

    def _record_native_caption_result(self, state: dict) -> None:
        normal = QRect(state.get("normal_geometry", self._normal_geometry))
        if self.isMaximized() or self.isFullScreen() or self._is_snap_geometry():
            if normal.isValid() and normal.width() >= self.minimumWidth() and normal.height() >= self.minimumHeight():
                self._normal_geometry = QRect(normal)
                self._remember_normal_frame_geometry(normal)
        elif bool(state.get("started_special", False)) and normal.isValid():
            current = QRect(self.geometry())
            self._normal_geometry = QRect(current.x(), current.y(), normal.width(), normal.height())
            self._remember_normal_frame_geometry(self._normal_geometry)
        elif self._should_store_as_normal_geometry():
            self._store_normal_geometry(QRect(self.geometry()))
        self.maximizedChanged.emit()
        self.geometryChanged.emit()

    def _begin_manual_restore_move(self, local_x: float = -1.0, local_y: float = -1.0) -> None:
        if sys.platform != "win32":
            return
        normal = self._best_special_restore_normal_geometry()
        self._normal_geometry = QRect(normal)
        self._remember_normal_frame_geometry(normal)
        try:
            cursor = QCursor.pos()
            start_inset = int(self._shadow_inset())
            start_content_width = max(1.0, float((self._quick_host.width() or self.geometry().width()) - start_inset * 2))
            self._move_state = {
                "manual_restore": True,
                "manual_restore_pending": True,
                "manual_restore_started": False,
                "caption_local_x": float(local_x),
                "caption_local_y": float(local_y),
                "start_content_width": float(start_content_width),
                "start_x": int(cursor.x()),
                "start_y": int(cursor.y()),
                "normal_geometry": QRect(normal),
                "local_x": 0.0,
                "local_y": 0.0,
                "width": int(normal.width()),
                "height": int(normal.height()),
            }
            try:
                self._native_agent_call("setMouseCaptureNative", True)
            except Exception:
                pass
            self._ensure_move_timer()
        except Exception:
            pass
        self.maximizedChanged.emit()
        self.geometryChanged.emit()

    def _start_manual_restore_drag(self, state: dict, cursor) -> None:
        normal = QRect(state.get("normal_geometry", self._normal_geometry))
        if not self._normal_geometry_candidate_is_usable(normal):
            normal = self._repair_normal_geometry(normal)
        target = self._restore_drag_target(
            normal,
            float(state.get("caption_local_x", -1.0)),
            float(state.get("caption_local_y", -1.0)),
            float(state.get("start_content_width", 0.0)) or None,
        )
        updates_enabled = self.updatesEnabled()
        self.setUpdatesEnabled(False)
        try:
            self._set_native_drag_restore_visual(True)
            applied = self._force_windows_normal_geometry(target, normal)
            if applied.isValid():
                target = QRect(applied)
            try:
                self.setGeometry(target)
            except Exception:
                pass
        finally:
            self.setUpdatesEnabled(updates_enabled)
            self.update()
        try:
            self._native_agent_call("setMouseCaptureNative", True)
        except Exception:
            pass
        state["manual_restore_pending"] = False
        state["manual_restore_started"] = True
        cursor = QCursor.pos()
        state["local_x"] = float(int(cursor.x()) - int(target.x()))
        state["local_y"] = float(int(cursor.y()) - int(target.y()))
        state["width"] = int(target.width())
        state["height"] = int(target.height())
        state["restore_geometry"] = QRect(target)
        state["last_geometry"] = QRect(target)
        self._remember_normal_frame_geometry(target)
        if self._begin_restored_native_caption_move(normal, target):
            return
        self._apply_system_move()
        QTimer.singleShot(0, self._reapply_manual_restore_move)
        QTimer.singleShot(16, self._reapply_manual_restore_move)
        self.maximizedChanged.emit()
        self.geometryChanged.emit()

    def _begin_restored_native_caption_move(self, normal: QRect, target: QRect) -> bool:
        if sys.platform != "win32":
            return False
        try:
            if not self._left_button_down():
                return False
            self._native_agent_call("setMouseCaptureNative", False)
            self._move_state = {
                "system_move": True,
                "normal_geometry": QRect(normal),
                "restore_geometry": QRect(target),
                "started_special": True,
            }
            self.maximizedChanged.emit()
            self.geometryChanged.emit()
            self._set_native_drag_restore_visual(False)
            self._ensure_move_timer()
            if self._native_agent_call("beginCaptionMoveNative") is not True:
                self._move_state = None
                self._stop_move_timer()
                return False
            if self._move_state and not self._left_button_down():
                self._finish_native_caption_move()
            return True
        except Exception:
            self._move_state = None
            self._stop_move_timer()
            return False

    def _reapply_manual_restore_move(self) -> None:
        state = self._move_state
        if not state or not bool(state.get("manual_restore_started", False)):
            return
        if not self._left_button_down():
            return
        self._apply_system_move()

    def _snap_target_for_cursor(self) -> tuple[QRect, str] | None:
        if sys.platform == "win32":
            return None
        area = self._screen_available_geometry()
        if area is None:
            return None
        try:
            cursor = QCursor.pos()
            if cursor.y() <= area.top() + self._snap_margin:
                return QRect(area), "top"
            half_w = max(self.minimumWidth(), area.width() // 2)
            half_w = min(half_w, area.width())
            if cursor.x() <= area.left() + self._snap_margin:
                return QRect(area.left(), area.top(), half_w, area.height()), "left"
            if cursor.x() >= area.right() - self._snap_margin:
                return QRect(area.right() - half_w + 1, area.top(), half_w, area.height()), "right"
        except Exception:
            return None
        return None

    def _update_snap_preview(self) -> None:
        target = self._snap_target_for_cursor()
        if target is None:
            self._hide_snap_preview()
            return
        snap_rect, snap_type = target
        if self._snap_preview_rect is not None and self._snap_preview_rect == snap_rect and self._snap_preview_type == snap_type:
            return
        self._snap_preview_rect = QRect(snap_rect)
        self._snap_preview_type = snap_type
        self.snapPreviewChanged.emit(self._window_key, snap_rect.x(), snap_rect.y(), snap_rect.width(), snap_rect.height(), True)

    def _hide_snap_preview(self) -> None:
        if self._snap_preview_rect is None and self._snap_preview_type is None:
            return
        self._snap_preview_rect = None
        self._snap_preview_type = None
        self.snapPreviewChanged.emit(self._window_key, 0, 0, 0, 0, False)

    def _save_geometry_to_settings(self) -> None:
        g = self._normal_geometry if self._normal_geometry.isValid() else self.geometry()
        if not self._normal_geometry_candidate_is_usable(g):
            g = self._repair_normal_geometry(g)
            self._normal_geometry = QRect(g)
            self._normal_frame_geometry = QRect(g)
        self._bridge.settings.set_value_py(f"{self._settings_key}/normalGeometry", {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()})
