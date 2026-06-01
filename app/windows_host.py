from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path

from PySide6.QtCore import QObject, Property, QRect, Qt, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication, QSurfaceFormat, QCursor
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QVBoxLayout, QWidget, QApplication

from .windows_compat import is_windows_11_or_newer, use_custom_window_shadow


if sys.platform == "win32":
    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi

    WM_NCHITTEST = 0x0084
    WM_NCCALCSIZE = 0x0083
    WM_NCLBUTTONDOWN = 0x00A1
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
    HTLEFT = 10
    HTRIGHT = 11
    HTTOP = 12
    HTTOPLEFT = 13
    HTTOPRIGHT = 14
    HTBOTTOM = 15
    HTBOTTOMLEFT = 16
    HTBOTTOMRIGHT = 17
    HTTRANSPARENT = -1
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
    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_LAYERED = 0x00080000
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

    class WINDOWPOS(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("hwndInsertAfter", wintypes.HWND),
            ("x", ctypes.c_int),
            ("y", ctypes.c_int),
            ("cx", ctypes.c_int),
            ("cy", ctypes.c_int),
            ("flags", ctypes.c_uint),
        ]
else:
    MSG = None


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
    captionPressed = Signal()

    def __init__(self, app: QApplication, engine, bridge, qml_dir: Path, parent=None):
        super().__init__(parent)
        self._app = app
        self._engine = engine
        self._bridge = bridge
        self._qml_dir = Path(qml_dir)
        self._resize_border = 2
        self._normal_geometry = QRect(160, 90, 1080, 700)
        self._normal_frame_geometry = QRect(self._normal_geometry)
        self._move_state: dict | None = None
        self._title_bar_height = 36
        self._caption_regions: list[tuple[int, int]] = []
        self._snap_preview_rect: QRect | None = None
        self._snap_preview_type: str | None = None
        self._snap_margin = 14
        self._always_on_top = False
        self._title = "QML无边框窗口模板"
        self.setProperty("windowKey", "main")
        self.setWindowTitle(self._title)
        self._custom_shadow_enabled = use_custom_window_shadow()
        self._shadow_input_passthrough = False
        self._last_shadow_inset = 0
        self._normalizing_snap_geometry = False
        self._vertical_snap_adjusted_rect: QRect | None = None

        self.setMinimumSize(640, 420)
        self.resize(1080, 700)
        flags = Qt.WindowType.Window | Qt.WindowType.FramelessWindowHint
        if self._custom_shadow_enabled:
            flags |= Qt.WindowType.NoDropShadowWindowHint
        self.setWindowFlags(flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)

        self._quick = QQuickWidget(engine, self)
        self._quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._quick.setClearColor(QColor(0, 0, 0, 0))
        self._quick.rootContext().setContextProperty("NativeHost", self)
        self._quick.rootContext().setContextProperty("App", bridge)
        self._quick.engine().addImportPath(str(self._qml_dir))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self._quick)

        self._move_timer = QTimer(self)
        self._move_timer.setInterval(12)
        self._move_timer.timeout.connect(self._tick_system_move)
        self._shadow_input_timer = QTimer(self)
        self._shadow_input_timer.setInterval(30)
        self._shadow_input_timer.timeout.connect(self._poll_shadow_input_passthrough)
        try:
            self._app.aboutToQuit.connect(self.shutdown)
        except Exception:
            pass

        self._restore_geometry_from_settings()
        self._quick.setSource(QUrl.fromLocalFile(str(self._qml_dir / "NativeMainContent.qml")))

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


    @Slot(result=bool)
    def isMaximizedState(self) -> bool:
        return bool(self._is_maximized_state() or self.isFullScreen())

    @Slot(result=bool)
    def isSnappedState(self) -> bool:
        return bool(self._is_snap_geometry())

    @Slot()
    def shutdown(self) -> None:
        self._move_state = None
        self._hide_snap_preview()
        if self._move_timer.isActive():
            self._move_timer.stop()
        self._set_shadow_input_passthrough(False)
        if self._shadow_input_timer.isActive():
            self._shadow_input_timer.stop()

    @Slot()
    @Slot(float, float)
    def beginSystemMove(self, local_x: float = -1.0, local_y: float = -1.0) -> None:
        if sys.platform != "win32":
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

    @Slot()
    def updateSystemMove(self) -> None:
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
            hwnd = wintypes.HWND(int(self.winId()))
            try:
                if self._left_button_down():
                    user32.SetCapture(hwnd)
            except Exception:
                pass
            flags = SWP_NOZORDER | SWP_NOOWNERZORDER
            if size_drift:
                user32.SetWindowPos(hwnd, None, int(x), int(y), int(width), int(height), flags)
            else:
                user32.SetWindowPos(hwnd, None, int(x), int(y), 0, 0, flags | SWP_NOSIZE)
            state["last_geometry"] = QRect(target)
            self.geometryChanged.emit()
        except Exception:
            self.setGeometry(target)
            state["last_geometry"] = QRect(target)
            self.geometryChanged.emit()

    def _apply_move_geometry(self, target: QRect, force_native: bool = False) -> None:
        if sys.platform == "win32" and force_native:
            try:
                hwnd = wintypes.HWND(int(self.winId()))
                user32.SetWindowPos(
                    hwnd,
                    None,
                    int(target.x()),
                    int(target.y()),
                    int(target.width()),
                    int(target.height()),
                    SWP_NOZORDER | SWP_NOOWNERZORDER | SWP_NOACTIVATE,
                )
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
                user32.ReleaseCapture()
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
        if sys.platform == "win32" and self._send_native_maximize_command():
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
        self.showMinimized()

    @Slot()
    def closeWindow(self) -> None:
        try:
            if self._bridge.tray.handleClosing(self):
                return
        except Exception:
            pass
        try:
            self._bridge.dialogs.closeAll()
        except Exception:
            pass
        self.close()

    @Slot(bool)
    def setAlwaysOnTop(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._always_on_top:
            return
        self._always_on_top = enabled
        if sys.platform == "win32":
            try:
                HWND_TOPMOST = -1
                HWND_NOTOPMOST = -2
                flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER
                user32.SetWindowPos(wintypes.HWND(int(self.winId())), HWND_TOPMOST if enabled else HWND_NOTOPMOST, 0, 0, 0, 0, flags)
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
        self.alwaysOnTopChanged.emit(enabled)

    @Slot()
    def activateHost(self) -> None:
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
        if sys.platform == "win32" and self.isVisible():
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
        if sys.platform == "win32":
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
        self.geometryChanged.emit()
        return super().moveEvent(event)

    def resizeEvent(self, event):  # noqa: N802
        normalized = self._normalize_vertical_snap_geometry()
        if not normalized and self._should_store_as_normal_geometry():
            self._store_normal_geometry(QRect(self.geometry()))
        self.maximizedChanged.emit()
        self.geometryChanged.emit()
        return super().resizeEvent(event)

    def changeEvent(self, event):  # noqa: N802
        super().changeEvent(event)
        self.maximizedChanged.emit()
        self.activeChanged.emit()

    def closeEvent(self, event):  # noqa: N802
        self._save_normal_geometry()
        self._save_geometry_to_settings()
        try:
            self._bridge.dialogs.closeAll()
        except Exception:
            pass
        return super().closeEvent(event)

    def showEvent(self, event):  # noqa: N802
        super().showEvent(event)
        self._apply_windows_chrome()
        self.maximizedChanged.emit()
        self.activeChanged.emit()

    def nativeEvent(self, event_type, message):  # noqa: N802
        if sys.platform != "win32" or MSG is None:
            return False, 0
        try:
            msg = MSG.from_address(int(message))
        except Exception:
            return False, 0
        if msg.message == WM_NCCALCSIZE:
            return True, 0
        if msg.message == WM_NCLBUTTONDOWN:
            try:
                if int(msg.wParam) == HTCAPTION:
                    if self._move_state and bool(self._move_state.get("manual_restore", False)):
                        return True, 0
                    self.captionPressed.emit()
                    local = self._caption_local_from_lparam(int(msg.lParam))
                    if local is not None and self._is_special_restore_state():
                        self._begin_manual_restore_move(float(local[0]), float(local[1]))
                        return True, 0
            except Exception:
                pass
        if msg.message == WM_MOVING:
            if self._move_state and bool(self._move_state.get("system_move", False)):
                self._update_snap_preview()
            return False, 0
        if msg.message == WM_WINDOWPOSCHANGED:
            if self._custom_shadow_enabled:
                QTimer.singleShot(0, self._normalize_vertical_snap_geometry)
            return False, 0
        if msg.message == WM_NCHITTEST:
            hit = self._hit_test(int(msg.lParam))
            if hit is not None:
                return True, hit
        return False, 0

    def _set_shadow_input_passthrough(self, enabled: bool) -> None:
        if sys.platform != "win32" or not self._custom_shadow_enabled:
            return
        enabled = bool(enabled)
        if enabled == self._shadow_input_passthrough:
            if enabled and not self._shadow_input_timer.isActive():
                self._shadow_input_timer.start()
            return
        try:
            hwnd = wintypes.HWND(int(self.winId()))
            if ctypes.sizeof(ctypes.c_void_p) == 8:
                get_long = user32.GetWindowLongPtrW
                set_long = user32.SetWindowLongPtrW
                get_long.restype = ctypes.c_longlong
                set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_longlong]
            else:
                get_long = user32.GetWindowLongW
                set_long = user32.SetWindowLongW
                get_long.restype = ctypes.c_long
                set_long.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
            style = int(get_long(hwnd, GWL_EXSTYLE))
            next_style = (style | WS_EX_LAYERED | WS_EX_TRANSPARENT) if enabled else (style & ~WS_EX_TRANSPARENT)
            if next_style != style:
                set_long(hwnd, GWL_EXSTYLE, next_style)
            self._shadow_input_passthrough = enabled
            if enabled:
                self._shadow_input_timer.start()
            elif self._shadow_input_timer.isActive():
                self._shadow_input_timer.stop()
        except Exception:
            pass

    def _poll_shadow_input_passthrough(self) -> None:
        if not self._shadow_input_passthrough:
            self._shadow_input_timer.stop()
            return
        try:
            rect = wintypes.RECT()
            hwnd = wintypes.HWND(int(self.winId()))
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                self._set_shadow_input_passthrough(False)
                return
            point = wintypes.POINT()
            if not user32.GetCursorPos(ctypes.byref(point)):
                self._set_shadow_input_passthrough(False)
                return
            px = int(point.x)
            py = int(point.y)
            if not (int(rect.left) <= px < int(rect.right) and int(rect.top) <= py < int(rect.bottom)):
                self._set_shadow_input_passthrough(False)
                return
            inset = self._shadow_inset()
            if inset <= 0:
                self._set_shadow_input_passthrough(False)
                return
            try:
                dpi = user32.GetDpiForWindow(hwnd)
                scale = max(1.0, float(dpi) / 96.0)
            except Exception:
                scale = 1.0
            inset_px = max(0, int(round(float(inset) * scale)))
            if int(rect.left) + inset_px <= px < int(rect.right) - inset_px and int(rect.top) + inset_px <= py < int(rect.bottom) - inset_px:
                self._set_shadow_input_passthrough(False)
        except Exception:
            self._set_shadow_input_passthrough(False)

    def _activate_window_beneath_point(self, x: int, y: int, excluded_hwnd: int) -> None:
        if sys.platform != "win32":
            return
        try:
            if not any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in (0x01, 0x02, 0x04)):
                return
            target = wintypes.HWND()

            @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            def enum_proc(hwnd, _lparam):
                if int(hwnd) == int(excluded_hwnd):
                    return True
                if not user32.IsWindowVisible(hwnd) or user32.IsIconic(hwnd):
                    return True
                rect = wintypes.RECT()
                if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return True
                if int(rect.left) <= int(x) < int(rect.right) and int(rect.top) <= int(y) < int(rect.bottom):
                    target.value = int(hwnd)
                    return False
                return True

            user32.EnumWindows(enum_proc, 0)
            if target.value:
                user32.SetForegroundWindow(target)
                user32.BringWindowToTop(target)
        except Exception:
            pass

    def _hit_test(self, lparam: int):
        try:
            rect = wintypes.RECT()
            hwnd = wintypes.HWND(int(self.winId()))
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            try:
                dpi = user32.GetDpiForWindow(hwnd)
                scale = max(1.0, float(dpi) / 96.0)
            except Exception:
                scale = 1.0
            border = max(2, int(round(self._resize_border * scale)))
            inset = self._shadow_inset()
            inset_px = max(0, int(round(float(inset) * scale)))
            visual_left = int(rect.left) + inset_px
            visual_top = int(rect.top) + inset_px
            visual_right = int(rect.right) - inset_px
            visual_bottom = int(rect.bottom) - inset_px
            if visual_right <= visual_left + border * 2 or visual_bottom <= visual_top + border * 2:
                visual_left = int(rect.left)
                visual_top = int(rect.top)
                visual_right = int(rect.right)
                visual_bottom = int(rect.bottom)
                inset_px = 0
            if inset_px > 0 and not (visual_left <= x < visual_right and visual_top <= y < visual_bottom):
                self._set_shadow_input_passthrough(False)
                self._activate_window_beneath_point(x, y, int(self.winId()))
                return HTTRANSPARENT
            self._set_shadow_input_passthrough(False)
            if not self._is_maximized_state() and not self.isFullScreen():
                left = visual_left <= x < visual_left + border
                right = visual_right - border <= x < visual_right
                top = visual_top <= y < visual_top + border
                bottom = visual_bottom - border <= y < visual_bottom
                if top and left:
                    return HTTOPLEFT
                if top and right:
                    return HTTOPRIGHT
                if bottom and left:
                    return HTBOTTOMLEFT
                if bottom and right:
                    return HTBOTTOMRIGHT
                if left:
                    return HTLEFT
                if right:
                    return HTRIGHT
                if top:
                    return HTTOP
                if bottom:
                    return HTBOTTOM
            local_x = (x - visual_left) / scale
            local_y = (y - visual_top) / scale
            if self._caption_hit_test(local_x, local_y):
                return HTCAPTION
        except Exception:
            return None
        return None

    def _shadow_inset(self) -> int:
        if not self._custom_shadow_enabled:
            return 0
        inset = 0
        try:
            root = self._quick.rootObject()
            if root is not None:
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
            root = self._quick.rootObject()
            if root is not None:
                inset = max(0, min(96, int(root.property("shadowVisualInset") or 0)))
                if inset > 0:
                    self._last_shadow_inset = inset
                    return inset
        except Exception:
            pass
        if self._last_shadow_inset > 0:
            return int(self._last_shadow_inset)
        return 32

    def _caption_hit_test(self, local_x: float, local_y: float) -> bool:
        if self.isFullScreen():
            return False
        try:
            if local_y < 0 or local_y > float(self._title_bar_height):
                return False
            if self._caption_regions:
                for left, right in self._caption_regions:
                    if float(left) <= local_x <= float(right):
                        return True
                return False
            right_block = 170
            content_width = max(0, int(self.width()) - self._shadow_inset() * 2)
            return 0 <= local_x <= max(0, content_width - right_block)
        except Exception:
            return False

    def _caption_local_from_lparam(self, lparam: int | None) -> tuple[float, float] | None:
        if sys.platform != "win32" or lparam is None:
            return None
        try:
            rect = wintypes.RECT()
            hwnd = wintypes.HWND(int(self.winId()))
            if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            x = ctypes.c_short(int(lparam) & 0xFFFF).value
            y = ctypes.c_short((int(lparam) >> 16) & 0xFFFF).value
            try:
                dpi = user32.GetDpiForWindow(hwnd)
                scale = max(1.0, float(dpi) / 96.0)
            except Exception:
                scale = 1.0
            inset_px = max(0, int(round(float(self._shadow_inset()) * scale)))
            visual_left = int(rect.left) + inset_px
            visual_top = int(rect.top) + inset_px
            visual_right = int(rect.right) - inset_px
            visual_bottom = int(rect.bottom) - inset_px
            if visual_right <= visual_left or visual_bottom <= visual_top:
                visual_left = int(rect.left)
                visual_top = int(rect.top)
            return (float(x - visual_left) / scale, float(y - visual_top) / scale)
        except Exception:
            return None

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

    def _restore_geometry_from_settings(self) -> None:
        settings = self._bridge.settings
        saved = settings.value_py("windows/main/normalGeometry", None)
        if isinstance(saved, dict):
            try:
                rect = QRect(int(saved.get("x", 160)), int(saved.get("y", 90)), int(saved.get("w", 1080)), int(saved.get("h", 700)))
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

    def _normalize_vertical_snap_geometry(self) -> bool:
        if self._normalizing_snap_geometry or not self._custom_shadow_enabled:
            return False
        if self._move_state and not bool(self._move_state.get("system_move", False)):
            return False
        geom = QRect(self.geometry())
        if self._snap_geometry_kind(geom) != "vertical":
            self._vertical_snap_adjusted_rect = None
            return False
        if self._vertical_snap_adjusted_rect is not None and geom == self._vertical_snap_adjusted_rect:
            return False
        inset = int(self._normal_shadow_inset())
        if inset <= 0 or geom.width() <= self.minimumWidth() + inset * 2:
            return False
        area = self._screen_available_geometry()
        if area is None:
            return False
        target = QRect(
            int(geom.x()) + inset,
            int(area.y()),
            max(self.minimumWidth(), int(geom.width()) - inset * 2),
            int(area.height()),
        )
        if target.x() < area.x():
            target.moveLeft(area.x())
        if target.right() > area.right():
            target.moveRight(area.right())
        if target == geom:
            return False
        self._normalizing_snap_geometry = True
        try:
            self.setGeometry(target)
            self._vertical_snap_adjusted_rect = QRect(target)
            return True
        except Exception:
            return False
        finally:
            self._normalizing_snap_geometry = False

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
            saved = self._bridge.settings.value_py("windows/main/normalGeometry", None)
            if not isinstance(saved, dict):
                return None
            rect = QRect(
                int(saved.get("x", 160)),
                int(saved.get("y", 90)),
                int(saved.get("w", 1080)),
                int(saved.get("h", 700)),
            )
            return rect if rect.isValid() else None
        except Exception:
            return None

    def _windows_restore_bounds(self) -> QRect | None:
        if sys.platform != "win32":
            return None
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
            root = self._quick.rootObject()
            if root is not None:
                root.setProperty("nativeDragRestoreVisual", bool(enabled) and bool(self._custom_shadow_enabled))
        except Exception:
            pass

    def _restore_drag_anchor(self, normal: QRect, local_x: float = -1.0, local_y: float = -1.0, current_content_width: float | None = None) -> tuple[float, float]:
        normal_inset = int(self._normal_shadow_inset())
        if current_content_width is None:
            current_inset = int(self._shadow_inset())
            current_content_width = float((self._quick.width() or self.geometry().width()) - current_inset * 2)
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
            hwnd = wintypes.HWND(hwnd_value)
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
            start_content_width = max(1.0, float((self._quick.width() or self.geometry().width()) - start_inset * 2))
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
                user32.SetCapture(wintypes.HWND(int(self.winId())))
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
            user32.SetCapture(wintypes.HWND(int(self.winId())))
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
        self._apply_system_move()
        QTimer.singleShot(0, self._reapply_manual_restore_move)
        QTimer.singleShot(16, self._reapply_manual_restore_move)
        self.maximizedChanged.emit()
        self.geometryChanged.emit()

    def _reapply_manual_restore_move(self) -> None:
        state = self._move_state
        if not state or not bool(state.get("manual_restore_started", False)):
            return
        if not self._left_button_down():
            return
        self._apply_system_move()

    def _snap_target_for_cursor(self) -> tuple[QRect, str] | None:
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
        self.snapPreviewChanged.emit("main", snap_rect.x(), snap_rect.y(), snap_rect.width(), snap_rect.height(), True)

    def _hide_snap_preview(self) -> None:
        if self._snap_preview_rect is None and self._snap_preview_type is None:
            return
        self._snap_preview_rect = None
        self._snap_preview_type = None
        self.snapPreviewChanged.emit("main", 0, 0, 0, 0, False)

    def _save_geometry_to_settings(self) -> None:
        g = self._normal_geometry if self._normal_geometry.isValid() else self.geometry()
        if not self._normal_geometry_candidate_is_usable(g):
            g = self._repair_normal_geometry(g)
            self._normal_geometry = QRect(g)
            self._normal_frame_geometry = QRect(g)
        self._bridge.settings.set_value_py("windows/main/normalGeometry", {"x": g.x(), "y": g.y(), "w": g.width(), "h": g.height()})
