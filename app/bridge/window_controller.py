from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

import shiboken6

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, QRect, QTimer, Qt, Signal, Slot, Property
from PySide6.QtGui import QCursor, QGuiApplication, QWindow

from app.window_policy import current_window_policy, external_shadow_supported, use_custom_window_chrome, use_custom_window_shadow
from app.windows_compat import is_windows_11_or_newer


if sys.platform == "win32":
    WM_SYSCOMMAND = 0x0112
    SC_MOVE = 0xF010
    SC_MAXIMIZE = 0xF030
    SC_RESTORE = 0xF120
    HTCAPTION = 2
    SWP_NOSIZE = 0x0001
    SWP_NOMOVE = 0x0002
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    SWP_FRAMECHANGED = 0x0020
    SWP_NOOWNERZORDER = 0x0200
    SW_SHOWNORMAL = 1
    SW_RESTORE = 9
    GWL_EXSTYLE = -20
    WS_EX_TRANSPARENT = 0x00000020
    WS_EX_LAYERED = 0x00080000
    WS_EX_NOACTIVATE = 0x08000000
    VK_LBUTTON = 0x01

    class MSG(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("message", wintypes.UINT),
            ("wParam", wintypes.WPARAM),
            ("lParam", wintypes.LPARAM),
            ("time", wintypes.DWORD),
            ("pt", wintypes.POINT),
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
else:  # pragma: no cover
    MSG = None
    WINDOWPOS = None


class _WindowsHitTestFilter(QAbstractNativeEventFilter):
    WM_NCCALCSIZE = 0x0083
    WM_NCHITTEST = 0x0084
    WM_NCLBUTTONDOWN = 0x00A1
    WM_ENTERSIZEMOVE = 0x0231
    WM_EXITSIZEMOVE = 0x0232
    WM_ACTIVATE = 0x0006
    WM_NCACTIVATE = 0x0086
    WM_WINDOWPOSCHANGING = 0x0046
    WM_WINDOWPOSCHANGED = 0x0047
    WM_SIZING = 0x0214
    WM_MOVING = 0x0216

    HTLEFT = 10
    HTRIGHT = 11
    HTTOP = 12
    HTTOPLEFT = 13
    HTTOPRIGHT = 14
    HTBOTTOM = 15
    HTBOTTOMLEFT = 16
    HTBOTTOMRIGHT = 17
    HTTRANSPARENT = -1

    def __init__(self, controller: "WindowController") -> None:
        super().__init__()
        self._controller = controller

    def nativeEventFilter(self, event_type, message):  # pragma: no cover - Windows runtime only
        if sys.platform != "win32" or MSG is None:
            return False, 0
        try:
            msg = MSG.from_address(int(message))
        except Exception:
            return False, 0

        if not getattr(msg, "hwnd", None):
            return False, 0
        try:
            hwnd = int(msg.hwnd)
        except Exception:
            return False, 0
        if not hwnd:
            return False, 0
        win = self._controller._hwnd_to_window.get(hwnd)
        if win is None:
            return False, 0
        if not self._controller._is_valid_window(win):
            self._controller._hwnd_to_window.pop(hwnd, None)
            return False, 0

        if msg.message in (self.WM_ACTIVATE, self.WM_NCACTIVATE):
            self._controller._stack_registered_shadow_for_target_hwnd(hwnd)
            return False, 0

        if msg.message == self.WM_WINDOWPOSCHANGED:
            self._controller._note_native_caption_windowpos_changed(win, hwnd)
            self._controller._sync_snapped_visual_for_window(win)
            return False, 0

        if msg.message == self.WM_ENTERSIZEMOVE:
            try:
                self._controller._native_size_move_kinds[hwnd] = self._controller._native_size_move_kinds.get(hwnd, "")
                self._controller._native_size_move_start_geometries.setdefault(hwnd, QRect(win.geometry()))
                self._controller._stack_registered_shadow_for_target_hwnd(hwnd)
                self._controller.nativeMoveStarted.emit(self._controller._key(win))
            except Exception:
                pass
            return False, 0

        if msg.message == self.WM_EXITSIZEMOVE:
            try:
                self._controller._stack_registered_shadow_for_target_hwnd(hwnd)
                kind = self._controller._native_size_move_kinds.pop(hwnd, "")
                start_geometry = self._controller._native_size_move_start_geometries.pop(hwnd, None)
                if kind == "sizing":
                    self._controller._finish_native_resize_from_event(win, start_geometry)
                else:
                    self._controller._finish_native_move_from_event(win, start_geometry)
                self._controller.nativeMoveFinished.emit(self._controller._key(win))
                self._controller._last_caption_hit_local_by_hwnd.pop(hwnd, None)
            except Exception:
                pass
            return False, 0

        if msg.message == self.WM_NCCALCSIZE:
            # Collapse the native non-client area. WS_THICKFRAME stays for
            # system move/resize/snap behavior; QML owns the visual chrome and
            # draws the custom shadow.
            return True, 0

        if msg.message == self.WM_NCLBUTTONDOWN:
            try:
                if int(msg.wParam) == HTCAPTION:
                    self._controller._stack_registered_shadow_for_target_hwnd(hwnd)
                    if self._controller._begin_windows_special_manual_caption_move(win, hwnd, int(msg.lParam)):
                        return True, 0
                    self._controller._prepare_native_caption_move(win, hwnd, int(msg.lParam))
                    self._controller.captionPressed.emit(self._controller._key(win))
            except Exception:
                pass
            return False, 0

        if msg.message == self.WM_MOVING:
            try:
                self._controller._native_size_move_kinds[hwnd] = "moving"
                state = self._controller._move_states.get(id(win))
                if state is not None and bool(state.get("system_move", False)):
                    state["dragging"] = True
                    self._controller._restore_native_caption_drag_visual(win, state)
                    self._controller._correct_special_caption_drag_anchor(win, state)
                    self._controller._update_move_snap_preview(win, state)
            except Exception:
                pass
            return False, 0

        if msg.message == self.WM_SIZING:
            self._controller._native_size_move_kinds[hwnd] = "sizing"
            return False, 0

        if msg.message == self.WM_NCHITTEST:
            # Let Windows own resize and caption dragging.  This avoids the
            # visible lag that can happen when a frameless QML MouseArea drives
            # setGeometry() manually while the scene graph is also relayouting
            # the page content, and it preserves Aero Snap/Snap Assist.
            hit = self._hit_test(hwnd, int(msg.lParam), win)
            if hit is not None:
                return True, int(hit)
            return False, 0
        return False, 0

    def _hit_test(self, hwnd: int, lparam: int, win: QWindow):
        try:
            rect = wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
                return None
        except Exception:
            return None

        x = ctypes.c_short(int(lparam) & 0xFFFF).value
        y = ctypes.c_short((int(lparam) >> 16) & 0xFFFF).value

        try:
            dpi = ctypes.windll.user32.GetDpiForWindow(wintypes.HWND(hwnd))
            scale = max(1.0, float(dpi) / 96.0)
        except Exception:
            scale = 1.0
        border = max(2, int(round(2 * scale)))
        inset_left, inset_top, inset_right, inset_bottom = self._controller._shadow_insets(win)
        left_px = max(0, int(round(float(inset_left) * scale)))
        top_px = max(0, int(round(float(inset_top) * scale)))
        right_px = max(0, int(round(float(inset_right) * scale)))
        bottom_px = max(0, int(round(float(inset_bottom) * scale)))
        visual_left = int(rect.left) + left_px
        visual_top = int(rect.top) + top_px
        visual_right = int(rect.right) - right_px
        visual_bottom = int(rect.bottom) - bottom_px
        if visual_right <= visual_left + border * 2 or visual_bottom <= visual_top + border * 2:
            visual_left = int(rect.left)
            visual_top = int(rect.top)
            visual_right = int(rect.right)
            visual_bottom = int(rect.bottom)
            left_px = top_px = right_px = bottom_px = 0

        if max(left_px, top_px, right_px, bottom_px) > 0 and not (visual_left <= x < visual_right and visual_top <= y < visual_bottom):
            self._controller._set_window_input_passthrough(hwnd, win, False)
            self._controller._activate_window_beneath_point(x, y, hwnd)
            return self.HTTRANSPARENT

        self._controller._set_window_input_passthrough(hwnd, win, False)
        if not self._controller._is_maximized_or_fullscreen(win):
            left = visual_left <= x < visual_left + border
            right = visual_right - border <= x < visual_right
            top = visual_top <= y < visual_top + border
            bottom = visual_bottom - border <= y < visual_bottom

            if top and left:
                return self.HTTOPLEFT
            if top and right:
                return self.HTTOPRIGHT
            if bottom and left:
                return self.HTBOTTOMLEFT
            if bottom and right:
                return self.HTBOTTOMRIGHT
            if left:
                return self.HTLEFT
            if right:
                return self.HTRIGHT
            if top:
                return self.HTTOP
            if bottom:
                return self.HTBOTTOM
        local_x = (x - visual_left) / scale
        local_y = (y - visual_top) / scale
        if self._caption_hit_test(win, local_x, local_y):
            self._controller._last_caption_hit_local_by_hwnd[hwnd] = (float(local_x), float(local_y))
            return HTCAPTION
        return None

    def _caption_hit_test(self, win: QWindow, local_x: float, local_y: float) -> bool:
        if self._controller._visibility_name(win) == "fullscreen":
            return False
        try:
            height = int(win.property("nativeTitleBarHeight") or 36)
        except Exception:
            height = 36
        height = max(24, min(80, height))
        if local_y < 0 or local_y > float(height):
            return False
        regions: list[tuple[int, int]] = []
        for left_name, right_name in (("nativeCaptionLeftA", "nativeCaptionRightA"), ("nativeCaptionLeftB", "nativeCaptionRightB")):
            try:
                left = int(win.property(left_name) or 0)
                right = int(win.property(right_name) or 0)
            except Exception:
                continue
            if right > left + 2:
                regions.append((left, right))
        if regions:
            return any(float(left) <= local_x <= float(right) for left, right in regions)
        try:
            inset_left, _inset_top, inset_right, _inset_bottom = self._controller._shadow_insets(win)
            content_width = max(0, int(win.width()) - int(inset_left) - int(inset_right))
            return 0 <= local_x <= max(0, content_width - 150)
        except Exception:
            return False


class WindowController(QObject):
    snapPreviewChanged = Signal(str, int, int, int, int, bool)
    nativeResizeChanged = Signal()
    snappedVisualChanged = Signal(str, bool)
    captionPressed = Signal(str)
    nativeMoveStarted = Signal(str)
    nativeMoveFinished = Signal(str)

    def __init__(self, settings, parent=None, native_window_shell: bool = False):
        super().__init__(parent)
        self._settings = settings
        self._native_window_shell = bool(native_window_shell)
        self._normal_geometries: dict[str, QRect] = {}
        self._normal_frame_geometries: dict[str, QRect] = {}
        self._drag_restore_geometries: dict[str, QRect] = {}
        self._move_states: dict[int, dict] = {}
        self._resize_states: dict[int, dict] = {}
        self._snap_rects: dict[int, QRect] = {}
        self._snap_types: dict[int, str] = {}
        self._snapped_normal_geometries: dict[str, QRect] = {}
        self._snapped_rects_by_key: dict[str, QRect] = {}
        self._snap_margin = 14
        self._native_frame_windows: set[int] = set()
        self._chrome_refresh_pending: set[int] = set()
        self._hwnd_to_window: dict[int, QWindow] = {}
        self._shadow_hwnd_by_target: dict[int, int] = {}
        self._shadow_margin_by_target: dict[int, int] = {}
        self._snapped_visual_keys: set[str] = set()
        self._snapped_visual_hold_keys: set[str] = set()
        self._last_shadow_insets_by_key: dict[str, int] = {}
        self._native_size_move_kinds: dict[int, str] = {}
        self._native_size_move_start_geometries: dict[int, QRect] = {}
        self._last_caption_hit_local_by_hwnd: dict[int, tuple[float, float]] = {}
        self._move_stabilize_tokens: dict[int, int] = {}
        self._input_transparent_hwnds: set[int] = set()

        self._session_timer = QTimer(self)
        # Keep this timer only as a release watchdog.  Moving the window from
        # both QML mouse events and this timer can produce a delayed one-frame
        # position correction after fast release, which feels like inertia/drift.
        self._session_timer.setInterval(12)
        self._session_timer.timeout.connect(self._tick_sessions)
        self._input_transparency_timer = QTimer(self)
        self._input_transparency_timer.setInterval(30)
        self._input_transparency_timer.timeout.connect(self._poll_input_transparency)

        self._native_filter = _WindowsHitTestFilter(self) if sys.platform == "win32" and not self._native_window_shell else None
        if self._native_filter is not None:
            try:
                app = QGuiApplication.instance()
                if app is not None:
                    app.installNativeEventFilter(self._native_filter)
                else:
                    self._native_filter = None
            except Exception:
                self._native_filter = None

    def set_native_window_shell(self, enabled: bool) -> None:
        old_native_resize = self.nativeResize
        self._native_window_shell = bool(enabled)
        if self._native_window_shell and self._native_filter is not None:
            try:
                app = QGuiApplication.instance()
                if app is not None:
                    app.removeNativeEventFilter(self._native_filter)
            except Exception:
                pass
            self._native_filter = None
        if old_native_resize != self.nativeResize:
            self.nativeResizeChanged.emit()

    @Slot()
    def shutdown(self) -> None:
        if self._session_timer.isActive():
            self._session_timer.stop()
        self._move_states.clear()
        self._resize_states.clear()
        self._snap_rects.clear()
        self._snap_types.clear()
        self._native_size_move_kinds.clear()
        self._native_size_move_start_geometries.clear()
        self._last_caption_hit_local_by_hwnd.clear()
        for hwnd in list(self._input_transparent_hwnds):
            self._set_window_input_passthrough(hwnd, None, False)
        self._input_transparent_hwnds.clear()
        if self._input_transparency_timer.isActive():
            self._input_transparency_timer.stop()
        if self._native_filter is not None:
            try:
                app = QGuiApplication.instance()
                if app is not None:
                    app.removeNativeEventFilter(self._native_filter)
            except Exception:
                pass
            self._native_filter = None

    @Property(bool, notify=nativeResizeChanged)
    def nativeResize(self) -> bool:
        # Windows gets native WM_NCHITTEST resizing.  Other platforms keep the
        # QML ResizeArea + startSystemResize/manual fallback path.
        return sys.platform == "win32" and not self._native_window_shell and self._native_filter is not None

    @Property(bool, constant=True)
    def nativeWindowShell(self) -> bool:
        return bool(self._native_window_shell)

    @Property(bool, constant=True)
    def customChromeEnabled(self) -> bool:
        return bool(use_custom_window_chrome())

    @Property(bool, constant=True)
    def customShadowEnabled(self) -> bool:
        return bool(use_custom_window_shadow())

    @Property(bool, constant=True)
    def externalShadowSupported(self) -> bool:
        return bool(external_shadow_supported())

    @Property(str, constant=True)
    def windowShadowPolicy(self) -> str:
        return current_window_policy().shadow_policy

    @Property(str, constant=True)
    def windowCornerPolicy(self) -> str:
        return current_window_policy().corner_policy

    @Property(str, constant=True)
    def windowPolicyReason(self) -> str:
        return current_window_policy().reason

    @Property(str, constant=True)
    def platformSessionType(self) -> str:
        return current_window_policy().session_type

    @Property(str, constant=True)
    def platformDesktop(self) -> str:
        return current_window_policy().desktop

    @Slot(QObject, QObject)
    @Slot(QObject, QObject, int)
    def stackShadowBehind(self, shadow_window: QObject, target_window: QObject, shadow_margin: int | None = None) -> None:
        if sys.platform != "win32":
            return
        shadow_hwnd, target_hwnd = self._register_shadow_hwnds(shadow_window, target_window, shadow_margin)
        if not shadow_hwnd or not target_hwnd:
            return
        self._stack_shadow_hwnd(shadow_hwnd, target_hwnd)

    @Slot(QObject, QObject)
    @Slot(QObject, QObject, int)
    def registerShadowWindow(self, shadow_window: QObject, target_window: QObject, shadow_margin: int | None = None) -> None:
        if sys.platform != "win32":
            return
        self._register_shadow_hwnds(shadow_window, target_window, shadow_margin)

    @Slot(QObject, QObject, int)
    def syncShadowWindow(self, shadow_window: QObject, target_window: QObject, shadow_margin: int) -> None:
        if sys.platform != "win32":
            return
        shadow_hwnd, target_hwnd = self._register_shadow_hwnds(shadow_window, target_window, shadow_margin)
        if not shadow_hwnd or not target_hwnd:
            return
        self._stack_shadow_hwnd(shadow_hwnd, target_hwnd)

    def _register_shadow_hwnds(self, shadow_window: QObject, target_window: QObject, shadow_margin: int | None = None) -> tuple[int, int]:
        shadow_hwnd = self._hwnd_for_object(shadow_window)
        target_hwnd = self._hwnd_for_object(target_window)
        if shadow_hwnd and target_hwnd and shadow_hwnd != target_hwnd:
            self._make_shadow_window_mouse_transparent(shadow_hwnd)
            self._shadow_hwnd_by_target[target_hwnd] = shadow_hwnd
            if shadow_margin is not None:
                try:
                    margin = max(0, min(128, int(shadow_margin)))
                except Exception:
                    margin = 38
                old_margin = self._shadow_margin_by_target.get(target_hwnd)
                self._shadow_margin_by_target[target_hwnd] = margin
            elif target_hwnd not in self._shadow_margin_by_target:
                self._shadow_margin_by_target[target_hwnd] = 38
            return int(shadow_hwnd), int(target_hwnd)
        return 0, 0

    def _make_shadow_window_mouse_transparent(self, shadow_hwnd: int) -> None:
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
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
            hwnd = wintypes.HWND(int(shadow_hwnd))
            ex_style = int(get_long(hwnd, GWL_EXSTYLE))
            next_style = ex_style | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE
            if next_style != ex_style:
                set_long(hwnd, GWL_EXSTYLE, next_style)
        except Exception:
            pass

    def _set_window_input_passthrough(self, hwnd_value: int, win: QWindow | None, enabled: bool) -> None:
        if sys.platform != "win32" or not hwnd_value:
            return
        try:
            user32 = ctypes.windll.user32
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
            hwnd = wintypes.HWND(int(hwnd_value))
            style = int(get_long(hwnd, GWL_EXSTYLE))
            next_style = (style | WS_EX_LAYERED | WS_EX_TRANSPARENT) if enabled else (style & ~WS_EX_TRANSPARENT)
            if next_style != style:
                set_long(hwnd, GWL_EXSTYLE, next_style)
            if enabled:
                self._input_transparent_hwnds.add(int(hwnd_value))
                self._hwnd_to_window[int(hwnd_value)] = win
                if not self._input_transparency_timer.isActive():
                    self._input_transparency_timer.start()
            else:
                self._input_transparent_hwnds.discard(int(hwnd_value))
                if not self._input_transparent_hwnds and self._input_transparency_timer.isActive():
                    self._input_transparency_timer.stop()
        except Exception:
            pass

    def _poll_input_transparency(self) -> None:
        if not self._input_transparent_hwnds:
            self._input_transparency_timer.stop()
            return
        point = wintypes.POINT()
        if not ctypes.windll.user32.GetCursorPos(ctypes.byref(point)):
            for hwnd_value in list(self._input_transparent_hwnds):
                self._set_window_input_passthrough(int(hwnd_value), self._hwnd_to_window.get(int(hwnd_value)), False)
            return
        px = int(point.x)
        py = int(point.y)
        for hwnd_value in list(self._input_transparent_hwnds):
            win = self._hwnd_to_window.get(int(hwnd_value))
            if not self._is_valid_window(win):
                self._set_window_input_passthrough(int(hwnd_value), win, False)
                continue
            try:
                rect = self._target_rect_from_hwnd(int(hwnd_value))
                if not rect.isValid() or not (rect.x() <= px < rect.x() + rect.width() and rect.y() <= py < rect.y() + rect.height()):
                    self._set_window_input_passthrough(int(hwnd_value), win, False)
                    continue
                inset_left, inset_top, inset_right, inset_bottom = self._shadow_insets(win)
                if max(inset_left, inset_top, inset_right, inset_bottom) <= 0:
                    self._set_window_input_passthrough(int(hwnd_value), win, False)
                    continue
                try:
                    dpi = ctypes.windll.user32.GetDpiForWindow(wintypes.HWND(int(hwnd_value)))
                    scale = max(1.0, float(dpi) / 96.0)
                except Exception:
                    scale = 1.0
                left_px = max(0, int(round(float(inset_left) * scale)))
                top_px = max(0, int(round(float(inset_top) * scale)))
                right_px = max(0, int(round(float(inset_right) * scale)))
                bottom_px = max(0, int(round(float(inset_bottom) * scale)))
                if rect.x() + left_px <= px < rect.x() + rect.width() - right_px and rect.y() + top_px <= py < rect.y() + rect.height() - bottom_px:
                    self._set_window_input_passthrough(int(hwnd_value), win, False)
            except Exception:
                self._set_window_input_passthrough(int(hwnd_value), win, False)

    def _activate_window_beneath_point(self, x: int, y: int, excluded_hwnd: int) -> None:
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
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

    def _stack_registered_shadow_for_target_hwnd(self, target_hwnd: int) -> None:
        shadow_hwnd = self._shadow_hwnd_by_target.get(int(target_hwnd))
        if shadow_hwnd:
            self._stack_shadow_hwnd(int(shadow_hwnd), int(target_hwnd))

    def _sync_registered_shadow_for_target_hwnd(self, target_hwnd: int, target_rect: QRect | None = None) -> None:
        _ = target_rect
        shadow_hwnd = self._shadow_hwnd_by_target.get(int(target_hwnd))
        if shadow_hwnd:
            self._stack_shadow_hwnd(int(shadow_hwnd), int(target_hwnd))

    def _stack_shadow_hwnd(self, shadow_hwnd: int, target_hwnd: int) -> None:
        try:
            user32 = ctypes.windll.user32
            if not user32.IsWindow(wintypes.HWND(shadow_hwnd)) or not user32.IsWindow(wintypes.HWND(target_hwnd)):
                self._shadow_hwnd_by_target.pop(int(target_hwnd), None)
                self._shadow_margin_by_target.pop(int(target_hwnd), None)
                return
            user32.SetWindowPos(
                wintypes.HWND(shadow_hwnd),
                wintypes.HWND(target_hwnd),
                0,
                0,
                0,
                0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_NOOWNERZORDER,
            )
        except Exception:
            pass

    def _target_rect_from_hwnd(self, hwnd: int) -> QRect:
        try:
            rect = wintypes.RECT()
            if ctypes.windll.user32.GetWindowRect(wintypes.HWND(int(hwnd)), ctypes.byref(rect)):
                return QRect(
                    int(rect.left),
                    int(rect.top),
                    int(rect.right - rect.left),
                    int(rect.bottom - rect.top),
                )
        except Exception:
            pass
        return QRect()

    def _target_rect_from_windowpos(self, target_hwnd: int, lparam: int) -> QRect | None:
        if sys.platform != "win32" or WINDOWPOS is None or not lparam:
            return None
        try:
            wp = WINDOWPOS.from_address(int(lparam))
            current = self._target_rect_from_hwnd(target_hwnd)
            flags = int(wp.flags)
            if flags & SWP_NOMOVE:
                x = current.x()
                y = current.y()
            else:
                x = int(wp.x)
                y = int(wp.y)
            if flags & SWP_NOSIZE:
                width = current.width()
                height = current.height()
            else:
                width = int(wp.cx)
                height = int(wp.cy)
            if width <= 0 or height <= 0:
                return current if current.isValid() else None
            return QRect(x, y, width, height)
        except Exception:
            return None

    def _target_rect_from_rect_lparam(self, lparam: int) -> QRect | None:
        if sys.platform != "win32" or not lparam:
            return None
        try:
            rect = wintypes.RECT.from_address(int(lparam))
            width = int(rect.right - rect.left)
            height = int(rect.bottom - rect.top)
            if width <= 0 or height <= 0:
                return None
            return QRect(int(rect.left), int(rect.top), width, height)
        except Exception:
            return None

    @Slot(QObject)
    def installNativeFrame(self, win: QWindow) -> None:
        if win is None:
            return
        self._native_frame_windows.add(id(win))
        QTimer.singleShot(0, lambda win=win: self._apply_native_frame(win))
        QTimer.singleShot(100, lambda win=win: self._apply_native_frame(win))

    @Slot(QObject)
    def refreshNativeFrame(self, win: QWindow) -> None:
        if win is None or id(win) not in self._native_frame_windows:
            return
        # Apply immediately.  Delayed DWM refreshes can make the shadow look as
        # if it lags behind during fast resize/move interactions.
        self._apply_native_frame(win)

    def _flush_chrome_refresh(self, win: QWindow, wid: int) -> None:
        self._chrome_refresh_pending.discard(wid)
        self._apply_native_frame(win)

    @Slot(QObject)
    def activateWindow(self, win: QWindow) -> None:
        if win is not None:
            self._raise_window(win)

    @Slot(QObject)
    def rememberNormalGeometry(self, win: QWindow) -> None:
        if win is None or self._is_maximized_or_fullscreen(win):
            return
        key = self._key(win)
        geom = self._coalesced_normal_geometry(key, QRect(win.geometry()))
        self._normal_geometries[key] = QRect(geom)
        self._remember_frame_geometry(key, win, geom)

    @Slot(QObject)
    def toggleMaximized(self, win: QWindow) -> None:
        if win is None:
            return
        key = self._key(win)
        if self._visibility_name(win) in {"maximized", "fullscreen"}:
            self._clear_snapped_state(key)
            if sys.platform == "win32" and self._send_windows_maximize_command(win, restore=True):
                pass
            else:
                win.showNormal()
                geom = self._normal_geometries.get(key)
                if geom is not None and geom.width() >= 320 and geom.height() >= 240:
                    QTimer.singleShot(0, lambda win=win, geom=QRect(geom): self._safe_set_geometry(win, geom))
            self.refreshNativeFrame(win)
            return
        self._clear_snapped_state(key)
        self.rememberNormalGeometry(win)
        if not (sys.platform == "win32" and self._send_windows_maximize_command(win, restore=False)):
            win.showMaximized()
        self._settings.set_value_py(f"windows/{key}/visibility", "maximized")
        self.refreshNativeFrame(win)

    @Slot(QObject, result=bool)
    def isMaximizedState(self, win: QWindow) -> bool:
        if win is None:
            return False
        return self._is_maximized_or_fullscreen(win)

    @Slot(QObject, result=bool)
    def isSnappedState(self, win: QWindow) -> bool:
        if win is None or not self._is_valid_window(win):
            return False
        return self._looks_like_snapped_window(win, self._key(win))

    @Slot(QObject, result=str)
    def snapState(self, win: QWindow) -> str:
        if win is None or not self._is_valid_window(win):
            return ""
        if self._native_interaction_active(win):
            return ""
        kind = self._snap_geometry_kind(win)
        return kind if kind in {"left", "right", "vertical"} else ""

    def _prepare_native_caption_move(self, win: QWindow, hwnd_value: int, lparam: int | None = None) -> None:
        if sys.platform != "win32" or not self._is_valid_window(win):
            return
        key = self._key(win)
        wid = id(win)
        self._hide_snap_preview(key, wid)
        start_visibility = self._visibility_name(win)
        if start_visibility == "fullscreen":
            return

        saved_visibility = str(self._settings.value_py(f"windows/{key}/visibility", "normal"))
        looks_snapped = self._looks_like_snapped_window(win, key)
        special = start_visibility in {"maximized", "fullscreen"} or looks_snapped
        if special:
            normal = self._best_unsnap_normal_geometry(
                win,
                key,
                (
                    self._snapped_normal_geometries.get(key),
                    self._normal_geometries.get(key),
                    self._load_normal_geometry(key, win),
                    self._windows_restore_bounds_for_window(win),
                ),
            )
        else:
            normal = self._coalesced_normal_geometry(key, QRect(win.geometry()))
            self._normal_geometries[key] = QRect(normal)
            self._remember_frame_geometry(key, win, normal)

        restore_geometry = QRect(normal)
        caption_local_x = 0.0
        caption_anchor_x = 0.0
        caption_anchor_y = 16.0
        restore_shadow_inset = 0
        if special:
            local_x, local_y = self._caption_restore_local_for_window(win, hwnd_value, lparam)
            restore_kind = "snapped" if looks_snapped else start_visibility
            caption_local_x = float(local_x)
            caption_anchor_x = self._caption_anchor_x_for_window(win, normal, local_x, restore_kind)
            caption_anchor_y = self._caption_anchor_y_for_window(win, local_y)
            restore_shadow_inset = self._normal_drag_shadow_inset(win)
            restore_geometry = self._restore_drag_target_for_window(win, normal, local_x, local_y, restore_kind)
            try:
                self._native_size_move_kinds[int(hwnd_value)] = "moving"
                self._native_size_move_start_geometries[int(hwnd_value)] = QRect(win.geometry())
                self._set_windows_restore_bounds(win, key, restore_geometry, wintypes.HWND(int(hwnd_value)), normal)
                self._sync_registered_shadow_for_target_hwnd(int(hwnd_value), restore_geometry)
            except Exception:
                pass
        else:
            try:
                self._native_size_move_kinds[int(hwnd_value)] = "moving"
                self._native_size_move_start_geometries.setdefault(int(hwnd_value), QRect(win.geometry()))
            except Exception:
                pass

        self._move_states[wid] = {
            "win": win,
            "key": key,
            "system_move": True,
            "dragging": False,
            "normal_geometry": QRect(restore_geometry),
            "unsnap_normal_geometry": QRect(normal),
            "restore_geometry": QRect(restore_geometry),
            "start_visibility": "snapped" if looks_snapped else start_visibility,
            "saved_visibility": saved_visibility,
            "started_special": special,
            "native_visual_restored": False,
            "caption_local_x": caption_local_x,
            "caption_anchor_x": caption_anchor_x,
            "caption_anchor_y": caption_anchor_y,
            "restore_shadow_inset": restore_shadow_inset,
        }
        self._ensure_session_timer()

    def _begin_windows_special_manual_caption_move(self, win: QWindow, hwnd_value: int, lparam: int | None = None) -> bool:
        if sys.platform != "win32" or not self._is_valid_window(win):
            return False
        key = self._key(win)
        wid = id(win)
        start_visibility = self._visibility_name(win)
        if start_visibility == "fullscreen":
            return False
        looks_snapped = self._looks_like_snapped_window(win, key)
        special = start_visibility in {"maximized"} or looks_snapped
        if not special:
            return False

        self._raise_window(win)
        normal = self._best_unsnap_normal_geometry(
            win,
            key,
            (
                self._snapped_normal_geometries.get(key),
                self._normal_geometries.get(key),
                self._load_normal_geometry(key, win),
                self._windows_restore_bounds_for_window(win),
            ),
        )
        if normal.width() < 320 or normal.height() < 240:
            return False

        restore_kind = "snapped" if looks_snapped else start_visibility
        local_x, local_y = self._caption_restore_local_for_window(win, hwnd_value, lparam)
        normal_inset = self._normal_drag_shadow_inset(win)
        anchor_x = self._caption_anchor_x_for_window(win, normal, local_x, restore_kind)
        anchor_y = self._caption_anchor_y_for_window(win, local_y)
        pos = QCursor.pos()

        try:
            self.captionPressed.emit(key)
            self._hide_snap_preview(key, wid)
            self._move_states[wid] = {
                "win": win,
                "key": key,
                "native_manual_restore": True,
                "native_manual_pending": True,
                "native_manual_started": False,
                "hwnd": int(hwnd_value),
                "system_move": False,
                "dragging": False,
                "restored": False,
                "start_visibility": "snapped" if looks_snapped else start_visibility,
                "started_special": True,
                "normal_geometry": QRect(normal),
                "unsnap_normal_geometry": QRect(normal),
                "restore_geometry": QRect(normal),
                "restore_kind": restore_kind,
                "caption_local_x": float(local_x),
                "caption_local_y": float(local_y),
                "local_x": float(normal_inset) + float(anchor_x),
                "local_y": float(normal_inset) + float(anchor_y),
                "start_pos_x": int(pos.x()),
                "start_pos_y": int(pos.y()),
                "last_x": int(win.x()),
                "last_y": int(win.y()),
                "caption_anchor_x": float(anchor_x),
                "caption_anchor_y": float(anchor_y),
                "restore_shadow_inset": int(normal_inset),
            }
            try:
                ctypes.windll.user32.SetCapture(wintypes.HWND(int(hwnd_value)))
            except Exception:
                pass
            self._ensure_session_timer()
            self._update_move_snap_preview(win, self._move_states[wid])
            return True
        except Exception:
            self._move_states.pop(wid, None)
            self._hide_snap_preview(key, wid)
            try:
                ctypes.windll.user32.ReleaseCapture()
            except Exception:
                pass
            try:
                win.setProperty("nativeInteractionActive", False)
                win.setProperty("nativeCaptionMovePending", False)
                win.setProperty("nativeDragRestoreVisual", False)
            except Exception:
                pass
            return False

    def _note_native_caption_windowpos_changed(self, win: QWindow, hwnd_value: int) -> None:
        if not self._is_valid_window(win):
            return
        state = self._move_states.get(id(win))
        if state is None or not bool(state.get("system_move", False)) or bool(state.get("dragging", False)):
            return
        try:
            if not bool(QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton):
                return
            start = self._native_size_move_start_geometries.get(int(hwnd_value))
            if start is None or not start.isValid():
                return
            if self._geometry_matches(win.geometry(), start, tolerance=2):
                return
            state["dragging"] = True
            self._restore_native_caption_drag_visual(win, state)
            self._correct_special_caption_drag_anchor(win, state)
            self._update_move_snap_preview(win, state)
        except Exception:
            pass

    def _restore_native_caption_drag_visual(self, win: QWindow, state: dict) -> None:
        if not self._is_valid_window(win) or bool(state.get("native_visual_restored", False)):
            return
        state["native_visual_restored"] = True
        if not bool(state.get("started_special", False)):
            return
        key = str(state.get("key") or self._key(win))
        restore_geometry = QRect(state.get("normal_geometry", win.geometry()))
        if restore_geometry.isValid():
            self._drag_restore_geometries[key] = QRect(restore_geometry)
            self._normal_geometries[key] = QRect(restore_geometry)
        self._clear_snapped_state(key)
        self._set_window_snapped_visual(win, False, suppress_shadow=False)
        self._settings.set_value_py(f"windows/{key}/visibility", "normal")

    def _restore_native_caption_click_visual(self, win: QWindow, key: str, state: dict) -> None:
        if not self._is_valid_window(win) or not bool(state.get("started_special", False)):
            return
        key = str(key)
        self._drag_restore_geometries.pop(key, None)
        normal = QRect(state.get("unsnap_normal_geometry", QRect()))
        if self._normal_geometry_candidate_is_usable(win, normal):
            self._normal_geometries[key] = QRect(normal)
            self._snapped_normal_geometries[key] = QRect(normal)

        visibility = self._visibility_name(win)
        if visibility in {"maximized", "fullscreen"}:
            self._settings.set_value_py(f"windows/{key}/visibility", visibility)
            self._set_window_snapped_visual(win, False, suppress_shadow=False)
            self._set_snapped_visual(key, False, force=True)
            return

        saved_visibility = str(state.get("saved_visibility", ""))
        if self._actual_geometry_looks_snapped(win) or str(state.get("start_visibility", "")) == "snapped":
            self._snapped_rects_by_key[key] = QRect(win.geometry())
            snap_kind = self._snap_geometry_kind(win)
            if snap_kind not in {"left", "right", "vertical"} and saved_visibility.startswith("snapped-"):
                snap_kind = saved_visibility.removeprefix("snapped-")
            if snap_kind not in {"left", "right", "vertical"}:
                snap_kind = self._snapped_side(win)
            self._settings.set_value_py(f"windows/{key}/visibility", f"snapped-{snap_kind}")
            self._set_window_snapped_visual(win, True, suppress_shadow=True)
            self._set_snapped_visual(key, True, force=True)
            QTimer.singleShot(0, lambda win=win: self._sync_snapped_visual_for_window(win))

    def _cursor_content_local_for_window(self, win: QWindow) -> tuple[float, float]:
        pos = QCursor.pos()
        try:
            left, top, _right, _bottom = self._shadow_insets(win)
            return float(pos.x() - int(win.x()) - int(left)), float(pos.y() - int(win.y()) - int(top))
        except Exception:
            return 0.0, 0.0

    def _caption_local_from_lparam(self, win: QWindow, hwnd_value: int, lparam: int | None) -> tuple[float, float] | None:
        if sys.platform != "win32" or lparam is None:
            return None
        try:
            hwnd = wintypes.HWND(int(hwnd_value))
            rect = wintypes.RECT()
            if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                return None
            x = ctypes.c_short(int(lparam) & 0xFFFF).value
            y = ctypes.c_short((int(lparam) >> 16) & 0xFFFF).value
            try:
                dpi = ctypes.windll.user32.GetDpiForWindow(hwnd)
                scale = max(1.0, float(dpi) / 96.0)
            except Exception:
                scale = 1.0

            inset_left, inset_top, inset_right, inset_bottom = self._shadow_insets(win)
            left_px = max(0, int(round(float(inset_left) * scale)))
            top_px = max(0, int(round(float(inset_top) * scale)))
            right_px = max(0, int(round(float(inset_right) * scale)))
            bottom_px = max(0, int(round(float(inset_bottom) * scale)))
            visual_left = int(rect.left) + left_px
            visual_top = int(rect.top) + top_px
            visual_right = int(rect.right) - right_px
            visual_bottom = int(rect.bottom) - bottom_px
            if visual_right <= visual_left or visual_bottom <= visual_top:
                visual_left = int(rect.left)
                visual_top = int(rect.top)

            return (float(x - visual_left) / scale, float(y - visual_top) / scale)
        except Exception:
            return None

    def _caption_restore_local_for_window(self, win: QWindow, hwnd_value: int, lparam: int | None = None) -> tuple[float, float]:
        local_from_message = self._caption_local_from_lparam(win, hwnd_value, lparam)
        if local_from_message is not None:
            return local_from_message
        try:
            local = self._last_caption_hit_local_by_hwnd.get(int(hwnd_value))
            if local is not None:
                return float(local[0]), float(local[1])
        except Exception:
            pass
        return self._cursor_content_local_for_window(win)

    @Slot(QObject, float, float)
    def beginMove(self, win: QWindow, local_x: float, local_y: float) -> None:
        if win is None:
            return
        self._raise_window(win)
        key = self._key(win)
        wid = id(win)
        self._hide_snap_preview(key, wid)
        start_visibility = self._visibility_name(win)
        if start_visibility == "fullscreen":
            return
        pos = QCursor.pos()
        snapped_normal = self._snapped_normal_geometries.get(key)
        snapped_rect = self._snapped_rects_by_key.get(key)
        looks_snapped = self._looks_like_snapped_window(win, key)
        if start_visibility == "normal" and (
            (snapped_normal is not None and (self._geometry_matches(win.geometry(), snapped_rect, tolerance=180) or looks_snapped))
        ):
            start_visibility = "snapped"
            candidate = QRect(snapped_normal) if snapped_normal is not None else self._load_normal_geometry(key, win)
            normal_at_start = self._repair_normal_geometry_for_unsnap(win, key, candidate)
        elif start_visibility == "normal":
            normal_at_start = QRect(win.geometry())
            self._normal_geometries[key] = QRect(normal_at_start)
            self._remember_frame_geometry(key, win, normal_at_start)
            self._clear_snapped_state(key)
        else:
            normal_at_start = self._normal_geometries.get(key) or self._load_normal_geometry(key, win)

        if sys.platform == "win32":
            if self._begin_windows_native_caption_move(win, key, local_x, local_y, start_visibility, normal_at_start):
                return
            if start_visibility != "normal":
                self._begin_windows_manual_restore_move(win, key, local_x, local_y, start_visibility, normal_at_start)
                return

        self._move_states[wid] = {
            "win": win,
            "key": key,
            "local_x": float(local_x),
            "local_y": float(local_y),
            "start_pos_x": pos.x(),
            "start_pos_y": pos.y(),
            "last_x": win.x(),
            "last_y": win.y(),
            "dragging": False,
            "restored": start_visibility == "normal",
            "start_visibility": start_visibility,
            "start_width": max(1, win.width()),
            "normal_geometry": QRect(normal_at_start),
        }
        self._ensure_session_timer()

    def _begin_windows_manual_restore_move(self, win: QWindow, key: str, local_x: float, local_y: float, start_visibility: str, normal_at_start: QRect) -> None:
        if not self._is_valid_window(win):
            return
        pos = QCursor.pos()
        normal = QRect(normal_at_start)
        target = self._restore_drag_target_for_window(win, normal, local_x, local_y, start_visibility)
        try:
            if sys.platform == "win32":
                hwnd_value = int(win.winId())
                hwnd = wintypes.HWND(hwnd_value)
                self._set_windows_restore_bounds(win, key, target, hwnd, normal)
                self._sync_registered_shadow_for_target_hwnd(hwnd_value, target)
                # Keep Qt's cached normal geometry in sync with the native
                # restore bounds before showNormal(). Without this, maximized
                # QML windows can paint the previous normal size for one frame
                # and then jump to the drag target.
                win.setGeometry(target)
                self._set_windows_restore_bounds(win, key, target, hwnd, target)
            win.showNormal()
            if not self._geometry_matches(win.geometry(), target, tolerance=1):
                win.setGeometry(target)
        except Exception:
            return
        self._clear_snapped_state(key)
        self._normal_geometries[key] = QRect(target)
        self._drag_restore_geometries[key] = QRect(target)
        self._settings.set_value_py(f"windows/{key}/visibility", "normal")
        self._move_states[id(win)] = {
            "win": win,
            "key": key,
            "local_x": float(pos.x() - target.x()),
            "local_y": float(pos.y() - target.y()),
            "start_pos_x": pos.x(),
            "start_pos_y": pos.y(),
            "last_x": target.x(),
            "last_y": target.y(),
            "dragging": True,
            "restored": True,
            "start_visibility": start_visibility,
            "start_width": max(1, normal.width()),
            "normal_geometry": QRect(normal),
            "restored_size": (int(normal.width()), int(normal.height())),
        }
        self._remember_frame_geometry(key, win, self._normal_geometries[key])
        self._ensure_session_timer()
        self.refreshNativeFrame(win)

    def _begin_windows_native_caption_move(self, win: QWindow, key: str, local_x: float, local_y: float, start_visibility: str, normal_at_start: QRect) -> bool:
        if sys.platform != "win32" or not self._is_valid_window(win):
            return False
        try:
            hwnd_value = int(win.winId())
        except Exception:
            return False
        if not hwnd_value:
            return False

        normal = QRect(normal_at_start)
        if normal.width() < 320 or normal.height() < 240:
            normal = self._load_normal_geometry(key, win)
        if normal.width() < 320 or normal.height() < 240:
            return False

        restore_geometry = QRect(normal)
        try:
            if start_visibility != "normal":
                restore_geometry = self._restore_drag_target_for_window(win, normal, local_x, local_y, start_visibility)
                self._set_windows_restore_bounds(win, key, restore_geometry, wintypes.HWND(hwnd_value), normal)
                self._drag_restore_geometries[key] = QRect(restore_geometry)
                self._normal_geometries[key] = QRect(restore_geometry)
                self._sync_registered_shadow_for_target_hwnd(hwnd_value, restore_geometry)
                self._clear_snapped_state(key)
                self._settings.set_value_py(f"windows/{key}/visibility", "normal")
            else:
                self._normal_geometries[key] = self._coalesced_normal_geometry(key, QRect(win.geometry()))
                self._remember_frame_geometry(key, win, self._normal_geometries[key])

            self._move_states[id(win)] = {
                "win": win,
                "key": key,
                "system_move": True,
                "dragging": True,
                "normal_geometry": QRect(restore_geometry),
                "start_visibility": start_visibility,
                "started_special": start_visibility != "normal",
                "caption_local_x": float(local_x),
                "caption_anchor_x": self._caption_anchor_x_for_window(win, normal, local_x, start_visibility),
                "caption_anchor_y": self._caption_anchor_y_for_window(win, local_y),
                "restore_shadow_inset": self._normal_drag_shadow_inset(win) if start_visibility != "normal" else 0,
            }
            self._ensure_session_timer()
            ctypes.windll.user32.ReleaseCapture()
            ctypes.windll.user32.SendMessageW(wintypes.HWND(hwnd_value), WM_SYSCOMMAND, SC_MOVE | HTCAPTION, 0)
            if id(win) in self._move_states and not bool(QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton):
                self._finish_move(win)
            return True
        except Exception:
            self._move_states.pop(id(win), None)
            self._hide_snap_preview(key, id(win))
            self._stop_session_timer_if_idle()
            return False

    def _begin_system_move(self, win: QWindow, key: str, local_x: float, local_y: float, start_visibility: str, normal_at_start: QRect) -> bool:
        if not self._is_valid_window(win):
            return False
        pos = QCursor.pos()
        try:
            normal = QRect(normal_at_start)
            # Restore maximized or snapped windows before entering the native
            # move loop. Recompute the mouse anchor after setting geometry so
            # the restored window does not jump under the cursor.
            if start_visibility != "normal":
                target = self._restore_drag_target_for_window(win, normal, local_x, local_y, start_visibility)
                win.showNormal()
                win.setGeometry(target)
                self._clear_snapped_state(key)
                self._normal_geometries[key] = QRect(normal)
                self._settings.set_value_py(f"windows/{key}/visibility", "normal")
            else:
                self._normal_geometries[key] = self._coalesced_normal_geometry(key, QRect(win.geometry()))

            started = False
            try:
                if hasattr(win, "startSystemMove"):
                    started = bool(win.startSystemMove())
            except Exception:
                started = False
            if not started:
                return False

            wid = id(win)
            self._move_states[wid] = {
                "win": win,
                "key": key,
                "system_move": True,
                "dragging": True,
                "normal_geometry": QRect(normal),
                "start_visibility": start_visibility,
            }
            self._ensure_session_timer()
            return True
        except Exception:
            return False

    @Slot(QObject)
    def updateMove(self, win: QWindow) -> None:
        if win is None:
            return
        state = self._move_states.get(id(win))
        if not state:
            return
        if bool(state.get("system_move", False)):
            return
        pos = QCursor.pos()
        moved = abs(pos.x() - int(state["start_pos_x"])) + abs(pos.y() - int(state["start_pos_y"]))
        if not bool(state.get("dragging")) and moved < 4:
            return
        state["dragging"] = True
        if not bool(state.get("restored", False)):
            self._restore_for_drag(win, state, pos.x(), pos.y())
            return
        new_x = int(pos.x() - float(state["local_x"]))
        new_y = int(pos.y() - float(state["local_y"]))
        if new_x != int(state.get("last_x", win.x())) or new_y != int(state.get("last_y", win.y())):
            try:
                win.setPosition(new_x, new_y)
            except Exception:
                try:
                    win.setGeometry(QRect(new_x, new_y, win.width(), win.height()))
                except Exception:
                    return
            state["last_x"] = new_x
            state["last_y"] = new_y
        self._update_move_snap_preview(win, state, pos)

    @Slot(QObject)
    def endMove(self, win: QWindow) -> None:
        if win is None:
            return
        self._finish_move(win)
        self._stop_session_timer_if_idle()

    @Slot(QObject, int)
    def beginResize(self, win: QWindow, edge_value: int) -> None:
        if win is None or self._is_maximized_or_fullscreen(win):
            return
        self._raise_window(win)
        self.rememberNormalGeometry(win)
        started = False
        try:
            if hasattr(win, "startSystemResize"):
                started = bool(win.startSystemResize(Qt.Edges(int(edge_value))))
        except Exception:
            started = False
        if started:
            # Native resize owns the drag session.  Do not also run the manual
            # timer, otherwise the QML scene can appear to resize independently
            # from the actual top-level window frame.
            return
        self._begin_manual_resize(win, int(edge_value))

    @Slot(QObject)
    def updateResize(self, win: QWindow) -> None:
        # Manual fallback path for platforms where startSystemResize() is not
        # available. On Windows, native WM_NCHITTEST is used and ResizeArea is
        # disabled, so this method normally becomes a no-op.
        if win is not None:
            self._apply_resize_state(win)

    @Slot(QObject)
    def endResize(self, win: QWindow) -> None:
        if win is not None:
            if id(win) in self._resize_states:
                self._finish_resize(win)
            elif not self._is_maximized_or_fullscreen(win):
                key = self._key(win)
                self._normal_geometries[key] = QRect(win.geometry())
                self._remember_frame_geometry(key, win, self._normal_geometries[key])
                self._settings.set_value_py(f"windows/{key}/normalGeometry", {"x": win.x(), "y": win.y(), "w": win.width(), "h": win.height()})
                self._settings.set_value_py(f"windows/{key}/visibility", "normal")
                self.refreshNativeFrame(win)
            self._stop_session_timer_if_idle()

    @Slot(QObject)
    def restoreWindowState(self, win: QWindow) -> None:
        if win is None:
            return
        key = self._key(win)
        saved = self._settings.value_py(f"windows/{key}/normalGeometry", None)
        if isinstance(saved, dict):
            try:
                geom = QRect(int(saved["x"]), int(saved["y"]), int(saved["w"]), int(saved["h"]))
                if geom.width() >= 320 and geom.height() >= 240:
                    if not self._normal_geometry_candidate_is_usable(win, geom):
                        geom = self._repair_normal_geometry_for_unsnap(win, key, geom)
                    win.setGeometry(geom)
                    self._normal_geometries[key] = QRect(geom)
                    self._normal_frame_geometries[key] = QRect(geom)
                    self._settings.set_value_py(f"windows/{key}/normalGeometry", {"x": geom.x(), "y": geom.y(), "w": geom.width(), "h": geom.height()})
            except Exception:
                pass
        visibility = self._settings.value_py(f"windows/{key}/visibility", "normal")
        always_on_top = bool(self._settings.value_py(f"windows/{key}/alwaysOnTop", False))
        if always_on_top:
            self.setAlwaysOnTop(win, True)
        if visibility == "maximized":
            QTimer.singleShot(0, lambda win=win: self._safe_window_call(win, "showMaximized"))
        elif visibility == "fullscreen":
            QTimer.singleShot(0, lambda win=win: self._safe_window_call(win, "showFullScreen"))
        else:
            QTimer.singleShot(0, lambda win=win: self._safe_window_call(win, "showNormal"))
        QTimer.singleShot(120, lambda win=win: self._apply_native_frame(win))

    @Slot(QObject)
    def restoreNativeManagedWindowState(self, win: QWindow) -> None:
        """Restore state without installing the legacy Python native frame."""
        if win is None:
            return
        key = self._key(win)
        saved = self._settings.value_py(f"windows/{key}/normalGeometry", None)
        if isinstance(saved, dict):
            try:
                geom = QRect(int(saved["x"]), int(saved["y"]), int(saved["w"]), int(saved["h"]))
                if geom.width() >= 320 and geom.height() >= 240:
                    win.setGeometry(geom)
                    self._normal_geometries[key] = QRect(geom)
                    self._normal_frame_geometries[key] = QRect(geom)
            except Exception:
                pass
        always_on_top = bool(self._settings.value_py(f"windows/{key}/alwaysOnTop", False))
        if always_on_top:
            self.setAlwaysOnTop(win, True)
        visibility = str(self._settings.value_py(f"windows/{key}/visibility", "normal"))
        if visibility == "maximized":
            QTimer.singleShot(0, lambda win=win: self._safe_window_call(win, "showMaximized"))
        elif visibility == "fullscreen":
            QTimer.singleShot(0, lambda win=win: self._safe_window_call(win, "showFullScreen"))
        else:
            QTimer.singleShot(0, lambda win=win: self._safe_window_call(win, "showNormal"))

    @Slot(QObject)
    def saveNativeManagedWindowState(self, win: QWindow) -> None:
        """Persist state for the QWindowKit/native shell."""
        if win is None:
            return
        key = self._key(win)
        visibility = self._visibility_name(win)
        if visibility not in ("maximized", "fullscreen", "minimized"):
            geometry = QRect(win.geometry())
            if geometry.width() >= 320 and geometry.height() >= 240:
                self._normal_geometries[key] = QRect(geometry)
                self._normal_frame_geometries[key] = QRect(geometry)
                self._settings.set_value_py(
                    f"windows/{key}/normalGeometry",
                    {"x": geometry.x(), "y": geometry.y(), "w": geometry.width(), "h": geometry.height()},
                )
            visibility = "normal"
        self._settings.set_value_py(f"windows/{key}/visibility", visibility)
        try:
            self._settings.set_value_py(f"windows/{key}/alwaysOnTop", bool(win.property("alwaysOnTop")))
        except Exception:
            pass

    @Slot(QObject)
    def saveWindowState(self, win: QWindow) -> None:
        if win is None:
            return
        key = self._key(win)
        visibility = self._visibility_name(win)
        if not self._is_maximized_or_fullscreen(win):
            if self._actual_geometry_looks_snapped(win):
                candidate = self._normal_geometries.get(key) or self._load_normal_geometry(key, win)
                geometry = self._repair_normal_geometry_for_unsnap(win, key, QRect(candidate))
                self._normal_geometries[key] = QRect(geometry)
                self._snapped_normal_geometries[key] = QRect(geometry)
                self._snapped_rects_by_key[key] = QRect(win.geometry())
                visibility = f"snapped-{self._snapped_side(win)}"
            elif key in self._snapped_normal_geometries and self._geometry_matches(win.geometry(), self._snapped_rects_by_key.get(key)):
                geometry = QRect(self._snapped_normal_geometries[key])
                visibility = str(self._settings.value_py(f"windows/{key}/visibility", "normal"))
            elif key in self._drag_restore_geometries:
                geometry = QRect(self._drag_restore_geometries[key])
                self._normal_geometries[key] = QRect(geometry)
                self._remember_frame_geometry(key, win, geometry)
                visibility = "normal"
            else:
                geometry = self._coalesced_normal_geometry(key, QRect(win.geometry()))
                self._normal_geometries[key] = QRect(geometry)
                self._remember_frame_geometry(key, win, geometry)
                self._clear_snapped_state(key)
                visibility = "normal"
        else:
            geometry = self._normal_geometries.get(key, win.geometry())
        self._settings.set_value_py(f"windows/{key}/normalGeometry", {"x": geometry.x(), "y": geometry.y(), "w": geometry.width(), "h": geometry.height()})
        self._settings.set_value_py(f"windows/{key}/visibility", visibility)

    @Slot(QObject, bool)
    def setAlwaysOnTop(self, win: QWindow, enabled: bool) -> None:
        if win is None:
            return
        flags = win.flags()
        if sys.platform == "win32" and self._is_valid_window(win):
            try:
                hwnd_value = int(win.winId())
                self._apply_hwnd_topmost(hwnd_value, enabled, activate=enabled)
                QTimer.singleShot(0, lambda hwnd_value=hwnd_value, enabled=enabled: self._apply_hwnd_topmost(hwnd_value, enabled, activate=False))
                QTimer.singleShot(80, lambda hwnd_value=hwnd_value, enabled=enabled: self._apply_hwnd_topmost(hwnd_value, enabled, activate=False))
                QTimer.singleShot(180, lambda hwnd_value=hwnd_value, enabled=enabled: self._apply_hwnd_topmost(hwnd_value, enabled, activate=False))
                QTimer.singleShot(90, lambda hwnd_value=hwnd_value: self._sync_registered_shadow_for_target_hwnd(hwnd_value))
            except Exception:
                pass
        else:
            if enabled:
                flags |= Qt.WindowType.WindowStaysOnTopHint
            else:
                flags &= ~Qt.WindowType.WindowStaysOnTopHint
            win.setFlags(flags)
        try:
            win.setProperty("alwaysOnTop", bool(enabled))
        except Exception:
            pass
        key = self._key(win)
        self._settings.set_value_py(f"windows/{key}/alwaysOnTop", bool(enabled))
        if not (sys.platform == "win32" and self._is_valid_window(win)):
            win.show()
            self._raise_window(win)
        self.refreshNativeFrame(win)

    @Slot(str, str, "QVariant")
    def handleWindowEvent(self, window_key: str, event_type: str, payload) -> None:
        _ = (window_key, event_type, payload)

    def _ensure_session_timer(self) -> None:
        if not self._session_timer.isActive():
            self._session_timer.start()

    def _stop_session_timer_if_idle(self) -> None:
        if not self._move_states and not self._resize_states and self._session_timer.isActive():
            self._session_timer.stop()

    def _tick_sessions(self) -> None:
        if not self._move_states and not self._resize_states:
            self._stop_session_timer_if_idle()
            return
        left_down = bool(QGuiApplication.mouseButtons() & Qt.MouseButton.LeftButton)
        if not left_down and sys.platform == "win32":
            try:
                left_down = bool(ctypes.windll.user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)
            except Exception:
                pass
        move_wins = [state.get("win") for state in list(self._move_states.values())]
        resize_wins = [state.get("win") for state in list(self._resize_states.values())]
        if not left_down:
            for win in move_wins:
                if win is not None:
                    self._finish_move(win)
            for win in resize_wins:
                if win is not None:
                    self._finish_resize(win)
            self._stop_session_timer_if_idle()
            return
        # Do not keep moving windows from the watchdog timer.  QML MouseArea
        # position events are the single source of truth while dragging.  The
        # timer only refreshes the snap preview at blocked screen edges,
        # including native caption moves, and detects releases outside the bar.
        pos = QCursor.pos()
        for state in list(self._move_states.values()):
            win = state.get("win")
            active_move = bool(state.get("dragging", False)) or bool(state.get("native_manual_pending", False))
            if win is not None and self._is_valid_window(win) and active_move:
                if bool(state.get("native_manual_restore", False)):
                    self._apply_native_manual_restore_move(win, state, pos)
                elif bool(state.get("system_move", False)):
                    self._correct_special_caption_drag_anchor(win, state)
                self._update_move_snap_preview(win, state, pos)
        for win in resize_wins:
            if win is not None:
                self._apply_resize_state(win)

    def _apply_native_manual_restore_move(self, win: QWindow, state: dict, pos) -> None:
        if not self._is_valid_window(win):
            return
        try:
            if bool(state.get("native_manual_pending", False)):
                moved = abs(int(pos.x()) - int(state.get("start_pos_x", pos.x()))) + abs(int(pos.y()) - int(state.get("start_pos_y", pos.y())))
                if moved < 4:
                    return
                if not self._start_native_manual_restore_drag(win, state, pos):
                    return
            new_x = int(pos.x() - float(state.get("local_x", 0.0)))
            new_y = int(pos.y() - float(state.get("local_y", 0.0)))
            if new_x == int(state.get("last_x", win.x())) and new_y == int(state.get("last_y", win.y())):
                self._apply_native_manual_restore_locked_size(win, state, new_x, new_y)
                return
            self._apply_native_manual_restore_locked_size(win, state, new_x, new_y)
            state["last_x"] = new_x
            state["last_y"] = new_y
        except Exception:
            pass

    def _apply_native_manual_restore_locked_size(self, win: QWindow, state: dict, x: int, y: int) -> None:
        restore_geom = QRect(state.get("restore_geometry", state.get("normal_geometry", win.geometry())))
        if not restore_geom.isValid():
            try:
                win.setPosition(int(x), int(y))
            except Exception:
                pass
            return
        target = QRect(int(x), int(y), int(restore_geom.width()), int(restore_geom.height()))
        try:
            current = QRect(win.geometry())
            size_drift = (
                abs(int(current.width()) - int(target.width())) > 1
                or abs(int(current.height()) - int(target.height())) > 1
            )
            position_drift = int(current.x()) != int(target.x()) or int(current.y()) != int(target.y())
            if size_drift:
                win.setGeometry(target)
            elif position_drift:
                win.setPosition(int(target.x()), int(target.y()))
        except Exception:
            try:
                win.setGeometry(target)
            except Exception:
                pass

    def _start_native_manual_restore_drag(self, win: QWindow, state: dict, pos) -> bool:
        if not self._is_valid_window(win):
            return False
        key = str(state.get("key") or self._key(win))
        normal = QRect(state.get("unsnap_normal_geometry", state.get("normal_geometry", win.geometry())))
        if normal.width() < 320 or normal.height() < 240:
            return False
        try:
            hwnd_value = int(state.get("hwnd") or int(win.winId()))
            local_x = float(state.get("caption_local_x", 0.0))
            local_y = float(state.get("caption_local_y", state.get("caption_anchor_y", 16.0)))
            restore_kind = str(state.get("restore_kind") or state.get("start_visibility") or "")
            target = self._restore_drag_target_for_window(win, normal, local_x, local_y, restore_kind)
            try:
                win.setProperty("nativeInteractionActive", True)
                win.setProperty("nativeDragRestoreVisual", bool(use_custom_window_shadow()))
            except Exception:
                pass
            self.nativeMoveStarted.emit(key)
            target = self._force_windows_normal_geometry(win, key, hwnd_value, target, normal)
            self._apply_native_frame(win)
            self._clear_snapped_state(key)
            self._set_window_snapped_visual(win, False, suppress_shadow=False)
            self._settings.set_value_py(f"windows/{key}/visibility", "normal")
            self._normal_geometries[key] = QRect(target)
            self._drag_restore_geometries[key] = QRect(target)
            state["native_manual_pending"] = False
            state["native_manual_started"] = True
            state["dragging"] = True
            state["restored"] = True
            state["normal_geometry"] = QRect(target)
            state["restore_geometry"] = QRect(target)
            state["local_x"] = float(pos.x() - int(target.x()))
            state["local_y"] = float(pos.y() - int(target.y()))
            state["last_x"] = int(target.x())
            state["last_y"] = int(target.y())
            self._apply_native_manual_restore_locked_size(win, state, int(target.x()), int(target.y()))
            self._update_move_snap_preview(win, state, pos)
            return True
        except Exception:
            return False

    def _begin_manual_resize(self, win: QWindow, edge_value: int) -> None:
        if not self._is_valid_window(win):
            return
        pos = QCursor.pos()
        geom = QRect(win.geometry())
        self._resize_states[id(win)] = {
            "win": win,
            "key": self._key(win),
            "edges": int(edge_value),
            "start_x": pos.x(),
            "start_y": pos.y(),
            "start_geom": QRect(geom),
            "last_geom": QRect(geom),
        }
        self._ensure_session_timer()

    def _apply_resize_state(self, win: QWindow) -> None:
        state = self._resize_states.get(id(win))
        if not state or not self._is_valid_window(win):
            return
        geom = QRect(state["start_geom"])
        pos = QCursor.pos()
        dx = pos.x() - int(state["start_x"])
        dy = pos.y() - int(state["start_y"])
        edges = int(state["edges"])
        left = bool(edges & self._edge_value(Qt.Edge.LeftEdge))
        right = bool(edges & self._edge_value(Qt.Edge.RightEdge))
        top = bool(edges & self._edge_value(Qt.Edge.TopEdge))
        bottom = bool(edges & self._edge_value(Qt.Edge.BottomEdge))
        min_w, min_h = self._minimum_size(win)
        x, y, w, h = geom.x(), geom.y(), geom.width(), geom.height()
        if left:
            nx = x + dx
            nw = w - dx
            if nw < min_w:
                nx = x + w - min_w
                nw = min_w
            x, w = nx, nw
        if right:
            w = max(min_w, w + dx)
        if top:
            ny = y + dy
            nh = h - dy
            if nh < min_h:
                ny = y + h - min_h
                nh = min_h
            y, h = ny, nh
        if bottom:
            h = max(min_h, h + dy)
        new_geom = QRect(int(x), int(y), int(w), int(h))
        if QRect(state.get("last_geom", QRect())) == new_geom:
            return
        try:
            win.setGeometry(new_geom)
            state["last_geom"] = QRect(new_geom)
        except Exception:
            pass

    def _finish_resize(self, win: QWindow) -> None:
        state = self._resize_states.pop(id(win), None)
        if state is None or not self._is_valid_window(win):
            return
        key = str(state.get("key") or self._key(win))
        if not self._is_maximized_or_fullscreen(win):
            self._normal_geometries[key] = QRect(win.geometry())
            self._remember_frame_geometry(key, win, self._normal_geometries[key])
            self._settings.set_value_py(f"windows/{key}/normalGeometry", {"x": win.x(), "y": win.y(), "w": win.width(), "h": win.height()})
            self._settings.set_value_py(f"windows/{key}/visibility", "normal")
        self.refreshNativeFrame(win)

    def _finish_move(self, win: QWindow) -> None:
        wid = id(win)
        state = self._move_states.pop(wid, None)
        key = self._key(win) if state is None else str(state["key"])
        snap_rect = self._snap_rects.pop(wid, None)
        snap_type = self._snap_types.pop(wid, None)
        if state is None:
            self.snapPreviewChanged.emit(key, 0, 0, 0, 0, False)
            return

        native_manual_restore = bool(state.get("native_manual_restore", False))

        def finish_native_manual_restore_visual() -> None:
            if not native_manual_restore:
                return
            try:
                if sys.platform == "win32":
                    ctypes.windll.user32.ReleaseCapture()
            except Exception:
                pass
            try:
                win.setProperty("nativeInteractionActive", False)
                win.setProperty("nativeCaptionMovePending", False)
                win.setProperty("nativeDragRestoreVisual", False)
            except Exception:
                pass
            if bool(state.get("native_manual_started", False)):
                self.nativeMoveFinished.emit(key)
            self.refreshNativeFrame(win)

        def apply_snap_result() -> bool:
            if snap_rect is None or not bool(state.get("dragging", False)):
                return False
            normal = QRect(state.get("normal_geometry", win.geometry()))
            if normal.width() >= 320 and normal.height() >= 240:
                self._normal_geometries[key] = QRect(normal)
            if snap_type == "top":
                self.snapPreviewChanged.emit(key, 0, 0, 0, 0, False)
                self._clear_snapped_state(key)
                try:
                    win.showMaximized()
                except Exception:
                    pass
                QTimer.singleShot(0, lambda win=win: self._safe_window_call(win, "showMaximized"))
                self._settings.set_value_py(f"windows/{key}/visibility", "maximized")
                QTimer.singleShot(100, lambda win=win: self._apply_native_frame(win))
                finish_native_manual_restore_visual()
                return True
            self._hold_snapped_visual(key, win)
            self.snapPreviewChanged.emit(key, 0, 0, 0, 0, False)
            try:
                win.showNormal()
                self._set_window_snapped_visual(win, True, suppress_shadow=True)
                self._set_snapped_visual(key, True, force=True)
                win.setGeometry(QRect(snap_rect))
            except Exception:
                pass
            self._snapped_normal_geometries[key] = QRect(normal)
            self._snapped_rects_by_key[key] = QRect(snap_rect)
            self._settings.set_value_py(f"windows/{key}/visibility", f"snapped-{snap_type}")
            QTimer.singleShot(0, lambda key=key: self._set_snapped_visual(key, True, force=True))
            QTimer.singleShot(0, lambda win=win, rect=QRect(snap_rect): self._apply_snapped_geometry(win, rect))
            QTimer.singleShot(40, lambda win=win, rect=QRect(snap_rect): self._apply_snapped_geometry(win, rect))
            QTimer.singleShot(120, lambda win=win, rect=QRect(snap_rect): self._apply_snapped_geometry(win, rect))
            QTimer.singleShot(240, lambda win=win, rect=QRect(snap_rect): self._apply_snapped_geometry(win, rect))
            QTimer.singleShot(80, lambda win=win, key=key: self._remember_actual_snapped_rect(win, key))
            QTimer.singleShot(100, lambda win=win: self._apply_native_frame(win))
            finish_native_manual_restore_visual()
            return True

        if bool(state.get("system_move", False)):
            if not bool(state.get("dragging", False)):
                self.snapPreviewChanged.emit(key, 0, 0, 0, 0, False)
                self._restore_native_caption_click_visual(win, key, state)
                return
            if bool(state.get("started_special", False)) and not bool(state.get("native_visual_restored", False)):
                self._restore_native_caption_drag_visual(win, state)
            if apply_snap_result():
                return
            self.snapPreviewChanged.emit(key, 0, 0, 0, 0, False)
            self._finish_system_move(win, key, state)
            return
        if apply_snap_result():
            return
        self.snapPreviewChanged.emit(key, 0, 0, 0, 0, False)
        if bool(state.get("dragging", False)) and not self._is_maximized_or_fullscreen(win):
            self._clear_snapped_state(key)
            self._drag_restore_geometries.pop(key, None)
            # Do not perform a final cursor-based setPosition here.  Fast drag
            # release can deliver one stale global cursor sample after the last
            # QML move event; applying it is exactly the visible delayed drift.
            # The last geometry already applied by updateMove() is authoritative.
            current_geom = QRect(win.geometry())
            if native_manual_restore:
                restore_geom = QRect(state.get("restore_geometry", state.get("normal_geometry", current_geom)))
                final_geom = QRect(
                    int(current_geom.x()),
                    int(current_geom.y()),
                    int(restore_geom.width()),
                    int(restore_geom.height()),
                )
                if (
                    abs(int(current_geom.width()) - int(restore_geom.width())) > 4
                    or abs(int(current_geom.height()) - int(restore_geom.height())) > 4
                ):
                    self._safe_set_geometry(win, final_geom)
            else:
                final_geom = self._coalesced_normal_geometry(key, current_geom)
            self._normal_geometries[key] = QRect(final_geom)
            self._settings.set_value_py(f"windows/{key}/visibility", "normal")
        finish_native_manual_restore_visual()

    def _finish_native_move_from_event(self, win: QWindow, start_geometry: QRect | None = None) -> None:
        if not self._is_valid_window(win):
            return
        state = self._move_states.get(id(win))
        if state is None:
            return
        if not bool(state.get("dragging", False)) and self._native_move_geometry_changed(win, start_geometry):
            state["dragging"] = True
        if (
            not bool(state.get("dragging", False))
            and bool(state.get("started_special", False))
            and self._visibility_name(win) == "normal"
            and not self._looks_like_snapped_window(win, self._key(win))
        ):
            state["dragging"] = True
        self._finish_move(win)
        self._stop_session_timer_if_idle()

    def _native_move_geometry_changed(self, win: QWindow, start_geometry: QRect | None) -> bool:
        if start_geometry is None or not start_geometry.isValid() or not self._is_valid_window(win):
            return False
        try:
            current = QRect(win.geometry())
            if not self._geometry_matches(current, start_geometry, tolerance=3):
                return True
        except Exception:
            pass
        try:
            frame = self._current_frame_geometry(win)
            if frame.isValid() and not self._geometry_matches(frame, start_geometry, tolerance=3):
                return True
        except Exception:
            pass
        return False

    def _finish_native_resize_from_event(self, win: QWindow, start_geometry: QRect | None = None) -> None:
        if not self._is_valid_window(win):
            return
        self._sync_snapped_visual_for_window(win)
        QTimer.singleShot(0, lambda win=win: self._sync_snapped_visual_for_window(win))
        QTimer.singleShot(60, lambda win=win, start=QRect(start_geometry) if start_geometry is not None else None: self._finalize_native_resize_result(win, start))

    def _finalize_native_resize_result(self, win: QWindow, start_geometry: QRect | None = None) -> None:
        if not self._is_valid_window(win):
            return
        key = self._key(win)
        kind = self._snap_geometry_kind(win)
        if kind == "vertical":
            normal = QRect(start_geometry) if start_geometry is not None and start_geometry.isValid() else self._normal_geometries.get(key, QRect(win.geometry()))
            if normal.width() >= 320 and normal.height() >= 240:
                self._snapped_normal_geometries[key] = QRect(normal)
                self._normal_geometries[key] = QRect(normal)
                self._settings.set_value_py(f"windows/{key}/normalGeometry", {"x": normal.x(), "y": normal.y(), "w": normal.width(), "h": normal.height()})
            self._snapped_rects_by_key[key] = QRect(win.geometry())
            self._settings.set_value_py(f"windows/{key}/visibility", "snapped-vertical")
            self._set_window_snapped_visual(win, True, suppress_shadow=True)
            self._set_snapped_visual(key, True, force=True)
            return
        if kind in {"left", "right"}:
            self._snapped_rects_by_key[key] = QRect(win.geometry())
            self._settings.set_value_py(f"windows/{key}/visibility", f"snapped-{kind}")
            return
        self._clear_snapped_state(key)
        if not self._is_maximized_or_fullscreen(win):
            geom = QRect(win.geometry())
            self._normal_geometries[key] = QRect(geom)
            self._remember_frame_geometry(key, win, geom)
            self._settings.set_value_py(f"windows/{key}/normalGeometry", {"x": geom.x(), "y": geom.y(), "w": geom.width(), "h": geom.height()})
            self._settings.set_value_py(f"windows/{key}/visibility", "normal")


    def _finish_system_move(self, win: QWindow, key: str, state: dict) -> None:
        if not self._is_valid_window(win):
            return
        # Defer one lightweight read so Windows has finished applying a native
        # snap/maximize result. We only record state; we do not set geometry.
        QTimer.singleShot(80, lambda win=win, key=key, state=dict(state): self._record_after_system_move(win, key, state))

    def _record_after_system_move(self, win: QWindow, key: str, state: dict) -> None:
        if not self._is_valid_window(win):
            return
        visibility = self._visibility_name(win)
        restored = self._drag_restore_geometries.pop(key, None)
        if visibility in {"maximized", "fullscreen"}:
            normal = QRect(state.get("normal_geometry", restored or self._normal_geometries.get(key, win.geometry())))
            if normal.width() >= 320 and normal.height() >= 240:
                self._normal_geometries[key] = QRect(normal)
                self._settings.set_value_py(f"windows/{key}/normalGeometry", {"x": normal.x(), "y": normal.y(), "w": normal.width(), "h": normal.height()})
            self._settings.set_value_py(f"windows/{key}/visibility", visibility)
            return
        if self._looks_like_snapped_window(win, key):
            normal = QRect(state.get("normal_geometry", restored or self._normal_geometries.get(key, win.geometry())))
            if normal.width() >= 320 and normal.height() >= 240:
                self._snapped_normal_geometries[key] = QRect(normal)
                self._normal_geometries[key] = QRect(normal)
                self._settings.set_value_py(f"windows/{key}/normalGeometry", {"x": normal.x(), "y": normal.y(), "w": normal.width(), "h": normal.height()})
            self._snapped_rects_by_key[key] = QRect(win.geometry())
            try:
                win.setProperty("snappedVisual", True)
            except Exception:
                pass
            self._set_snapped_visual(key, True)
            self._apply_snapped_geometry(win, QRect(win.geometry()))
            QTimer.singleShot(80, lambda win=win: self._apply_snapped_geometry(win, QRect(win.geometry())))
            side = self._snapped_side(win)
            self._settings.set_value_py(f"windows/{key}/visibility", f"snapped-{side}")
            return
        self._clear_snapped_state(key)
        if restored is not None:
            current = QRect(win.geometry())
            geom = QRect(current.x(), current.y(), restored.width(), restored.height())
        else:
            geom = self._coalesced_normal_geometry(key, QRect(win.geometry()))
        self._normal_geometries[key] = QRect(geom)
        self._remember_frame_geometry(key, win, geom)
        self._settings.set_value_py(f"windows/{key}/normalGeometry", {"x": geom.x(), "y": geom.y(), "w": geom.width(), "h": geom.height()})
        self._settings.set_value_py(f"windows/{key}/visibility", "normal")

    def _set_windows_restore_bounds(self, win: QWindow, key: str, client_geom: QRect, hwnd, reference_client: QRect | None = None) -> QRect:
        user32 = ctypes.windll.user32
        outer = self._frame_geometry_for_client(key, client_geom, reference_client, hwnd)

        try:
            class WINDOWPLACEMENT(ctypes.Structure):
                _fields_ = [
                    ("length", wintypes.UINT),
                    ("flags", wintypes.UINT),
                    ("showCmd", wintypes.UINT),
                    ("ptMinPosition", wintypes.POINT),
                    ("ptMaxPosition", wintypes.POINT),
                    ("rcNormalPosition", wintypes.RECT),
                ]

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

    def _force_windows_normal_geometry(self, win: QWindow, key: str, hwnd_value: int, client_geom: QRect, reference_client: QRect | None = None) -> QRect:
        geom = self._clamp_restore_geometry_to_screen(win, client_geom)
        hwnd = wintypes.HWND(int(hwnd_value))
        outer = self._frame_geometry_for_client(key, geom, reference_client, hwnd)
        applied = QRect(geom)
        try:
            user32 = ctypes.windll.user32

            class WINDOWPLACEMENT(ctypes.Structure):
                _fields_ = [
                    ("length", wintypes.UINT),
                    ("flags", wintypes.UINT),
                    ("showCmd", wintypes.UINT),
                    ("ptMinPosition", wintypes.POINT),
                    ("ptMaxPosition", wintypes.POINT),
                    ("rcNormalPosition", wintypes.RECT),
                ]

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
            actual = self._target_rect_from_hwnd(int(hwnd_value))
            if (
                actual.isValid()
                and abs(int(actual.width()) - int(geom.width())) <= 4
                and abs(int(actual.height()) - int(geom.height())) <= 4
            ):
                applied = QRect(actual)
        except Exception:
            try:
                win.showNormal()
                win.setGeometry(QRect(geom))
            except Exception:
                pass
        return QRect(applied)

    def _windows_restore_bounds_for_window(self, win: QWindow) -> QRect | None:
        if sys.platform != "win32" or not self._is_valid_window(win):
            return None
        try:
            class WINDOWPLACEMENT(ctypes.Structure):
                _fields_ = [
                    ("length", wintypes.UINT),
                    ("flags", wintypes.UINT),
                    ("showCmd", wintypes.UINT),
                    ("ptMinPosition", wintypes.POINT),
                    ("ptMaxPosition", wintypes.POINT),
                    ("rcNormalPosition", wintypes.RECT),
                ]

            placement = WINDOWPLACEMENT()
            placement.length = ctypes.sizeof(WINDOWPLACEMENT)
            hwnd = wintypes.HWND(int(win.winId()))
            if not ctypes.windll.user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
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

    def _current_frame_geometry(self, win: QWindow) -> QRect:
        if sys.platform == "win32" and self._is_valid_window(win):
            try:
                rect = wintypes.RECT()
                hwnd = wintypes.HWND(int(win.winId()))
                if ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    return QRect(
                        int(rect.left),
                        int(rect.top),
                        int(rect.right - rect.left),
                        int(rect.bottom - rect.top),
                    )
            except Exception:
                pass
        try:
            frame = win.frameGeometry()
            if frame.isValid():
                return QRect(frame)
        except Exception:
            pass
        try:
            return QRect(win.geometry())
        except Exception:
            return QRect()

    def _remember_frame_geometry(self, key: str, win: QWindow, client_geom: QRect) -> None:
        frame = self._current_frame_geometry(win)
        if not frame.isValid() or not client_geom.isValid():
            return
        try:
            dw = int(frame.width()) - int(client_geom.width())
            dh = int(frame.height()) - int(client_geom.height())
            if 0 <= dw <= 128 and 0 <= dh <= 128:
                self._normal_frame_geometries[str(key)] = QRect(frame)
        except Exception:
            pass

    def _frame_geometry_for_client(self, key: str, client_geom: QRect, reference_client: QRect | None = None, hwnd=None) -> QRect:
        if sys.platform == "win32" and hwnd is not None:
            try:
                return self._native_outer_rect_for_client(hwnd, client_geom)
            except Exception:
                pass
        key = str(key)
        reference = QRect(reference_client) if reference_client is not None else self._normal_geometries.get(key)
        frame = self._normal_frame_geometries.get(key)
        if frame is not None and reference is not None and frame.isValid() and reference.isValid():
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

    def _native_outer_rect_for_client(self, hwnd, client_geom: QRect) -> QRect:
        # The native event filter returns 0 for WM_NCCALCSIZE, so our visible
        # QML bounds are already the HWND bounds. AdjustWindowRectEx would add
        # an invisible frame that Windows later subtracts, causing repeated
        # maximize/snap drag-restores to shrink by a few pixels each time.
        return QRect(client_geom)

    def _restore_for_drag(self, win: QWindow, state: dict, cursor_x: int, cursor_y: int) -> None:
        normal = QRect(state["normal_geometry"])
        full_width = max(1, int(state.get("start_width", win.width())))
        ratio_x = max(0.0, min(1.0, float(state["local_x"]) / full_width))
        new_x = int(cursor_x - normal.width() * ratio_x)
        new_y = int(cursor_y - min(float(state["local_y"]), 38.0))
        try:
            win.showNormal()
            win.setGeometry(new_x, new_y, normal.width(), normal.height())
        except Exception:
            return
        state["restored"] = True
        self._clear_snapped_state(str(state.get("key") or self._key(win)))
        self._remember_frame_geometry(str(state.get("key") or self._key(win)), win, normal)
        state["local_x"] = float(cursor_x - new_x)
        state["local_y"] = float(cursor_y - new_y)
        state["last_x"] = new_x
        state["last_y"] = new_y
        self._raise_window(win)
        self.refreshNativeFrame(win)

    def _restore_drag_target_for_window(self, win: QWindow, normal: QRect, local_x: float, local_y: float, start_visibility: str = "") -> QRect:
        pos = QCursor.pos()
        _current_left, current_top, _current_right, _current_bottom = self._shadow_insets(win)
        normal_inset = self._normal_drag_shadow_inset(win)
        anchor_x = self._caption_anchor_x_for_window(win, normal, local_x, start_visibility)
        anchor_y = self._caption_anchor_y_for_window(win, local_y)
        return self._clamp_restore_geometry_to_screen(win, QRect(
            int(pos.x() - normal_inset - anchor_x),
            int(pos.y() - normal_inset - anchor_y + int(current_top)),
            int(normal.width()),
            int(normal.height()),
        ))

    def _clamp_restore_geometry_to_screen(self, win: QWindow, geom: QRect) -> QRect:
        rect = QRect(geom)
        try:
            area = self._screen_available_geometry(win)
            if area is None:
                return rect
            min_w, min_h = self._minimum_size(win)
            width = max(min_w, min(int(rect.width()), int(area.width())))
            height = max(min_h, min(int(rect.height()), int(area.height())))
            rect.setWidth(width)
            rect.setHeight(height)
            return rect
        except Exception:
            return rect

    def _caption_anchor_x_for_window(self, win: QWindow, normal: QRect, local_x: float, start_visibility: str = "") -> float:
        normal_inset = self._normal_drag_shadow_inset(win)
        normal_content_width = max(1.0, float(int(normal.width()) - normal_inset * 2))
        try:
            x = float(local_x)
        except Exception:
            x = normal_content_width * 0.5
        visibility = str(start_visibility).lower()
        if visibility == "maximized" or visibility.startswith("snapped") or visibility in {"left", "right", "vertical"}:
            current_left, _current_top, current_right, _current_bottom = self._shadow_insets(win)
            current_content_width = max(1.0, float(int(win.width()) - int(current_left) - int(current_right)))
            ratio_x = max(0.0, min(1.0, x / current_content_width))
            return normal_content_width * ratio_x
        return max(0.0, min(x, normal_content_width))

    def _caption_anchor_y_for_window(self, win: QWindow, local_y: float) -> float:
        try:
            title_height = max(24, min(96, int(win.property("nativeTitleBarHeight") or 38)))
        except Exception:
            title_height = 38
        try:
            y = float(local_y)
        except Exception:
            y = 16.0
        return max(6.0, min(y, float(max(6, title_height - 1))))

    def _correct_special_caption_drag_anchor(self, win: QWindow, state: dict) -> None:
        if not self._is_valid_window(win):
            return
        if not bool(state.get("started_special", False)):
            return
        start_visibility = str(state.get("start_visibility", ""))
        if start_visibility == "normal":
            return
        try:
            inset = int(state.get("restore_shadow_inset", self._normal_drag_shadow_inset(win)))
            anchor_x = float(state.get("caption_anchor_x", 0.0))
            anchor_y = float(state.get("caption_anchor_y", 16.0))
            cursor = QCursor.pos()
            current = QRect(win.geometry())
            frame = self._current_frame_geometry(win)
            base_x = int(frame.x()) if frame.isValid() else int(current.x())
            base_y = int(frame.y()) if frame.isValid() else int(current.y())
            dx = int(round(float(cursor.x()) - (float(base_x) + float(inset) + anchor_x)))
            dy = int(round(float(cursor.y()) - (float(base_y) + float(inset) + anchor_y)))
            if abs(dx) <= 1 and abs(dy) <= 1:
                return
            win.setPosition(int(current.x()) + dx, int(current.y()) + dy)
        except Exception:
            pass

    def _normal_drag_shadow_inset(self, win: QWindow) -> int:
        if not self._is_valid_window(win) or not use_custom_window_shadow():
            return 0
        try:
            inset = max(0, min(96, int(win.property("normalShadowVisualInset") or 0)))
            if inset > 0:
                return inset
        except Exception:
            pass
        cached = self._last_shadow_insets_by_key.get(self._key(win), 0)
        if cached > 0:
            return int(cached)
        return 32

    def _stabilize_after_move(self, win: QWindow, geom: QRect) -> None:
        # Disabled: delayed post-release setPosition can look like inertial drift.
        return

    def _snap_target_for_cursor(self, win: QWindow, cursor_x: int, cursor_y: int) -> tuple[QRect, str] | None:
        screen = win.screen() or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if screen is None:
            return None
        area = screen.availableGeometry()
        if cursor_y <= area.top() + self._snap_margin:
            return QRect(area), "top"
        min_w, _ = self._minimum_size(win)
        half_w = max(min_w, area.width() // 2)
        half_w = min(half_w, area.width())
        if cursor_x <= area.left() + self._snap_margin:
            return QRect(area.left(), area.top(), half_w, area.height()), "left"
        if cursor_x >= area.right() - self._snap_margin:
            return QRect(area.right() - half_w + 1, area.top(), half_w, area.height()), "right"
        return None

    def _update_move_snap_preview(self, win: QWindow, state: dict, pos=None) -> None:
        if not self._is_valid_window(win):
            return
        if pos is None:
            pos = QCursor.pos()
        key = str(state.get("key") or self._key(win))
        wid = id(win)
        target = self._snap_target_for_cursor(win, int(pos.x()), int(pos.y()))
        if target is not None:
            snap_rect, snap_type = target
            old = self._snap_rects.get(wid)
            self._snap_rects[wid] = QRect(snap_rect)
            self._snap_types[wid] = snap_type
            if old is None or old != snap_rect:
                self.snapPreviewChanged.emit(key, snap_rect.x(), snap_rect.y(), snap_rect.width(), snap_rect.height(), True)
        else:
            self._hide_snap_preview(key, wid)

    def _hide_snap_preview(self, key: str, wid: int) -> None:
        if wid in self._snap_rects:
            self._snap_rects.pop(wid, None)
            self._snap_types.pop(wid, None)
            self.snapPreviewChanged.emit(key, 0, 0, 0, 0, False)

    def _set_snapped_visual(self, key: str, snapped: bool, force: bool = False) -> None:
        key = str(key)
        if snapped:
            if force or key not in self._snapped_visual_keys:
                self._snapped_visual_keys.add(key)
                self.snappedVisualChanged.emit(key, True)
            return
        if force or key in self._snapped_visual_keys:
            self._snapped_visual_keys.discard(key)
            self.snappedVisualChanged.emit(key, False)

    def _hold_snapped_visual(self, key: str, win: QWindow | None = None, msec: int = 320) -> None:
        key = str(key)
        self._snapped_visual_hold_keys.add(key)
        self._set_window_snapped_visual(win, True, suppress_shadow=True)
        self._set_snapped_visual(key, True, force=True)
        QTimer.singleShot(msec, lambda key=key, win=win: self._release_snapped_visual_hold(key, win))

    def _release_snapped_visual_hold(self, key: str, win: QWindow | None = None) -> None:
        self._snapped_visual_hold_keys.discard(str(key))
        if self._is_valid_window(win):
            self._sync_snapped_visual_for_window(win)

    def _sync_snapped_visual_for_window(self, win: QWindow) -> None:
        if not self._is_valid_window(win):
            return
        key = self._key(win)
        if self._native_interaction_active(win) and key not in self._snapped_visual_hold_keys:
            return
        try:
            if key in self._snapped_visual_hold_keys:
                snapped = True
            else:
                snapped_rect = self._snapped_rects_by_key.get(key)
                snapped = (
                    not self._is_maximized_or_fullscreen(win)
                    and (
                        self._geometry_matches(win.geometry(), snapped_rect, tolerance=12)
                        or self._actual_geometry_looks_snapped(win)
                    )
                )
        except Exception:
            snapped = False
        try:
            self._set_window_snapped_visual(win, snapped, suppress_shadow=False)
        except Exception:
            pass
        self._set_snapped_visual(key, snapped)

    def _native_interaction_active(self, win: QWindow) -> bool:
        if sys.platform != "win32" or not self._is_valid_window(win):
            return False
        try:
            return int(win.winId()) in self._native_size_move_kinds
        except Exception:
            return False

    def _clear_snapped_state(self, key: str) -> None:
        key = str(key)
        had = key in self._snapped_normal_geometries or key in self._snapped_rects_by_key
        self._snapped_visual_hold_keys.discard(key)
        self._snapped_normal_geometries.pop(key, None)
        self._snapped_rects_by_key.pop(key, None)
        if had or key in self._snapped_visual_keys:
            self._set_snapped_visual(key, False)


    def _remember_actual_snapped_rect(self, win: QWindow, key: str) -> None:
        if self._is_valid_window(win) and str(self._settings.value_py(f"windows/{key}/visibility", "")).startswith("snapped-"):
            self._snapped_rects_by_key[str(key)] = QRect(win.geometry())

    def _apply_snapped_geometry(self, win: QWindow, rect: QRect) -> None:
        if not self._is_valid_window(win):
            return
        try:
            key = self._key(win)
            self._set_window_snapped_visual(win, True, suppress_shadow=True)
            self._set_snapped_visual(key, True, force=True)
            win.setGeometry(QRect(rect))
            self._snapped_rects_by_key[key] = QRect(rect)
        except Exception:
            pass

    def _set_window_snapped_visual(self, win: QWindow | None, snapped: bool, suppress_shadow: bool = False) -> None:
        if not self._is_valid_window(win):
            return
        try:
            if suppress_shadow and snapped:
                win.setProperty("snapShadowSuppressed", True)
            win.setProperty("snappedVisual", bool(snapped))
            if not snapped:
                win.setProperty("snappedVisualKind", "")
                win.setProperty("snapShadowSuppressed", False)
        except Exception:
            pass

    def _looks_like_snapped_window(self, win: QWindow, key: str) -> bool:
        try:
            return (
                self._actual_geometry_looks_snapped(win)
                or self._geometry_matches(win.geometry(), self._snapped_rects_by_key.get(str(key)), tolerance=12)
            )
        except Exception:
            return False

    def _actual_geometry_looks_snapped(self, win: QWindow) -> bool:
        try:
            return self._snap_geometry_kind(win) in {"left", "right", "vertical"}
        except Exception:
            return False

    def _snapped_side(self, win: QWindow) -> str:
        try:
            area = self._screen_available_geometry(win)
            if area is not None:
                geom = win.geometry()
                kind = self._snap_geometry_kind(win, geom)
                if kind == "vertical":
                    return "vertical"
                if kind == "right" or abs(geom.right() - area.right()) <= 12:
                    return "right"
        except Exception:
            pass
        return "left"

    def _screen_available_geometry(self, win: QWindow) -> QRect | None:
        try:
            screen = win.screen() or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            return screen.availableGeometry() if screen is not None else None
        except Exception:
            return None

    def _snap_geometry_kind(self, win: QWindow, rect: QRect | None = None) -> str:
        area = self._screen_available_geometry(win)
        if area is None:
            return ""
        rect = QRect(rect or win.geometry())
        tol = 8
        same_height = abs(rect.y() - area.y()) <= tol and abs(rect.height() - area.height()) <= tol
        half_tol = max(tol, int(area.width() * 0.04))
        left_half = abs(rect.x() - area.x()) <= tol and abs(rect.width() - area.width() / 2) <= half_tol
        right_half = abs(rect.right() - area.right()) <= tol and abs(rect.width() - area.width() / 2) <= half_tol
        near_full = (
            abs(rect.x() - area.x()) <= tol
            and abs(rect.y() - area.y()) <= tol
            and abs(rect.width() - area.width()) <= tol
            and abs(rect.height() - area.height()) <= tol
        )
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

    def _normal_geometry_candidate_is_usable(self, win: QWindow, candidate: QRect | None) -> bool:
        if candidate is None:
            return False
        try:
            geom = QRect(candidate)
            min_w, min_h = self._minimum_size(win)
            if not geom.isValid() or geom.width() < min_w or geom.height() < min_h:
                return False
            if self._normal_geometry_looks_shadow_shrunk(win, geom):
                return False
            area = self._screen_available_geometry(win)
            if area is not None:
                near_full_size = geom.width() >= area.width() - 32 and geom.height() >= area.height() - 32
                if near_full_size:
                    return False
            return self._snap_geometry_kind(win, geom) == ""
        except Exception:
            return False

    def _best_unsnap_normal_geometry(self, win: QWindow, key: str, candidates) -> QRect:
        fallback: QRect | None = None
        for candidate in candidates:
            if candidate is None:
                continue
            geom = QRect(candidate)
            if fallback is None and geom.isValid():
                fallback = QRect(geom)
            if self._normal_geometry_candidate_is_usable(win, geom):
                return QRect(geom)
        if fallback is not None:
            return self._repair_normal_geometry_for_unsnap(win, key, fallback)
        return self._repair_normal_geometry_for_unsnap(win, key, QRect(win.geometry()))

    def _repair_normal_geometry_for_unsnap(self, win: QWindow, key: str, candidate: QRect) -> QRect:
        try:
            screen = win.screen() or QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
            area = screen.availableGeometry() if screen is not None else None
            geom = win.geometry()
            min_w, min_h = self._minimum_size(win)
            # If an older version accidentally saved the half-screen snapped rect
            # as normalGeometry, replace it with a useful default normal size.
            looks_like_bad_saved = False
            if area is not None:
                looks_like_bad_saved = (abs(candidate.height() - area.height()) <= 24 and candidate.width() <= max(geom.width() + 80, int(area.width() * 0.62)))
            if candidate.width() < min_w or candidate.height() < min_h or looks_like_bad_saved or self._normal_geometry_looks_shadow_shrunk(win, candidate):
                normal_inset = self._normal_drag_shadow_inset(win)
                available_w = int(area.width()) if area is not None else max(1280, int(geom.width()), min_w + 240)
                available_h = int(area.height()) if area is not None else max(820, int(geom.height()), min_h + 160)
                w = max(min_w, min(1280, max(min_w + 240, int(available_w * 0.42))))
                h = max(min_h, min(820, max(min_h + 160, int(available_h * 0.48))))
                if area is not None:
                    w = min(w, max(min_w, int(area.width()) - normal_inset * 2))
                    h = min(h, max(min_h, int(area.height()) - normal_inset * 2))
                x = geom.x() + max(24, (geom.width() - w) // 2)
                y = geom.y() + 28
                if area is not None:
                    min_x = int(area.x()) - normal_inset
                    max_x = int(area.x() + area.width()) - int(w) + normal_inset
                    min_y = int(area.y()) - normal_inset
                    max_y = int(area.y() + area.height()) - int(h) + normal_inset
                    x = max(min_x, min(int(x), max_x))
                    y = max(min_y, min(int(y), max_y))
                return QRect(x, y, w, h)
            return QRect(candidate)
        except Exception:
            return QRect(candidate)

    def _normal_geometry_looks_shadow_shrunk(self, win: QWindow, geom: QRect) -> bool:
        try:
            min_w, min_h = self._minimum_size(win)
            normal_inset = self._normal_drag_shadow_inset(win)
            if normal_inset <= 0:
                return False
            return (
                int(geom.width()) <= int(min_w) + normal_inset * 2 + 8
                or int(geom.height()) <= int(min_h) + normal_inset * 2 + 8
            )
        except Exception:
            return False

    def _coalesced_normal_geometry(self, key: str, candidate: QRect) -> QRect:
        """Keep intentional normal size stable across Windows maximize/snap restore.

        On frameless Windows, the native restore/drag loop may report the QML
        window a few pixels smaller than the remembered normal size because the
        non-client frame and DWM shadow are being collapsed.  If we save that
        tiny delta every time, each maximize -> drag-restore cycle looks like
        the window shrinks by one ring.  Preserve the previous width/height for
        small deltas, but keep the new x/y so normal dragging still records the
        final position.  Real user resizes are larger and still overwrite size.
        """
        key = str(key)
        previous = self._normal_geometries.get(key)
        if previous is None:
            return QRect(candidate)
        try:
            dw = abs(int(candidate.width()) - int(previous.width()))
            dh = abs(int(candidate.height()) - int(previous.height()))
            if dw <= 72 and dh <= 72:
                return QRect(int(candidate.x()), int(candidate.y()), int(previous.width()), int(previous.height()))
        except Exception:
            pass
        return QRect(candidate)

    def _geometry_matches(self, geom: QRect, target: QRect | None, tolerance: int = 3) -> bool:
        if target is None:
            return False
        try:
            return (abs(int(geom.x()) - int(target.x())) <= tolerance
                    and abs(int(geom.y()) - int(target.y())) <= tolerance
                    and abs(int(geom.width()) - int(target.width())) <= tolerance
                    and abs(int(geom.height()) - int(target.height())) <= tolerance)
        except Exception:
            return False

    def _apply_hwnd_topmost(self, hwnd: int, enabled: bool, activate: bool = False) -> None:
        if sys.platform != "win32" or not hwnd:
            return
        try:
            user32 = ctypes.windll.user32
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
            self._sync_registered_shadow_for_target_hwnd(int(hwnd))
        except Exception:
            pass

    def _raise_window(self, win: QWindow) -> None:
        for name in ("raise_", "raise"):
            try:
                fn = getattr(win, name, None)
                if callable(fn):
                    fn()
                    break
            except Exception:
                pass
        try:
            win.requestActivate()
        except Exception:
            pass

    def _key(self, win: QWindow) -> str:
        return str(win.property("windowKey") or win.objectName() or "window")

    def _shadow_inset(self, win: QWindow) -> int:
        return max(self._shadow_insets(win))

    def _shadow_insets(self, win: QWindow) -> tuple[int, int, int, int]:
        if not self._is_valid_window(win):
            return (0, 0, 0, 0)
        try:
            if self._is_maximized_or_fullscreen(win):
                return (0, 0, 0, 0)
            fallback = max(0, min(96, int(win.property("nativeShadowInset") or 0)))

            def read_inset(name: str) -> int:
                value = win.property(name)
                if value is None:
                    return fallback
                return max(0, min(96, int(value)))

            left = read_inset("nativeShadowInsetLeft")
            top = read_inset("nativeShadowInsetTop")
            right = read_inset("nativeShadowInsetRight")
            bottom = read_inset("nativeShadowInsetBottom")
            max_inset = max(left, top, right, bottom)
            if max_inset > 0:
                self._last_shadow_insets_by_key[self._key(win)] = max_inset
            return (left, top, right, bottom)
        except Exception:
            return (0, 0, 0, 0)

    def _is_maximized_or_fullscreen(self, win: QWindow) -> bool:
        return self._visibility_name(win) in {"maximized", "fullscreen"}

    def _visibility_name(self, win: QWindow) -> str:
        try:
            v = win.visibility()
        except Exception:
            return "normal"
        if sys.platform == "win32" and self._is_valid_window(win):
            try:
                if ctypes.windll.user32.IsZoomed(wintypes.HWND(int(win.winId()))):
                    return "maximized"
            except Exception:
                pass
        if v == QWindow.Visibility.Maximized:
            return "maximized"
        if v == QWindow.Visibility.FullScreen:
            return "fullscreen"
        if v == QWindow.Visibility.Minimized:
            return "minimized"
        s = str(v).lower()
        if "maximized" in s:
            return "maximized"
        if "fullscreen" in s or "full_screen" in s:
            return "fullscreen"
        if "minimized" in s:
            return "minimized"
        return "normal"

    def _send_windows_maximize_command(self, win: QWindow, restore: bool) -> bool:
        if not self._is_valid_window(win):
            return False
        try:
            hwnd = wintypes.HWND(int(win.winId()))
            if not hwnd:
                return False
            ctypes.windll.user32.SendMessageW(hwnd, WM_SYSCOMMAND, SC_RESTORE if restore else SC_MAXIMIZE, 0)
            return True
        except Exception:
            return False

    def _load_normal_geometry(self, key: str, win: QWindow) -> QRect:
        saved = self._settings.value_py(f"windows/{key}/normalGeometry", None)
        if isinstance(saved, dict):
            try:
                geom = QRect(int(saved["x"]), int(saved["y"]), int(saved["w"]), int(saved["h"]))
                if self._normal_geometry_candidate_is_usable(win, geom):
                    return geom
                return self._repair_normal_geometry_for_unsnap(win, key, geom)
            except Exception:
                pass
        return QRect(win.x(), win.y(), max(900, win.width()), max(560, win.height()))

    def _is_valid_window(self, win: QWindow) -> bool:
        try:
            return win is not None and shiboken6.isValid(win)
        except Exception:
            return False

    def _hwnd_for_object(self, obj: QObject) -> int:
        try:
            if obj is None or not shiboken6.isValid(obj):
                return 0
        except Exception:
            return 0
        for name in ("winId", "effectiveWinId"):
            try:
                fn = getattr(obj, name, None)
                if callable(fn):
                    hwnd = int(fn())
                    if hwnd:
                        return hwnd
            except Exception:
                pass
        return 0

    def _safe_window_call(self, win: QWindow, method_name: str) -> None:
        if not self._is_valid_window(win):
            return
        try:
            method = getattr(win, method_name, None)
            if callable(method):
                method()
        except Exception:
            pass

    def _safe_set_geometry(self, win: QWindow, geom: QRect) -> None:
        if not self._is_valid_window(win):
            return
        try:
            win.setGeometry(geom)
        except Exception:
            pass

    def _minimum_size(self, win: QWindow) -> tuple[int, int]:
        min_w = 320
        min_h = 240
        for attr in ("minimumWidth", "minimumHeight"):
            try:
                value = getattr(win, attr)
                if callable(value):
                    value = value()
                if attr == "minimumWidth":
                    min_w = max(min_w, int(value))
                else:
                    min_h = max(min_h, int(value))
            except Exception:
                pass
        return min_w, min_h

    def _edge_value(self, edge) -> int:
        try:
            return int(edge.value)
        except Exception:
            try:
                return int(edge)
            except Exception:
                return 0

    def _apply_native_frame(self, win: QWindow) -> None:
        if not self._is_valid_window(win) or sys.platform != "win32":
            return
        try:
            hwnd = int(win.winId())
        except Exception:
            return
        if not hwnd:
            return
        self._hwnd_to_window[hwnd] = win
        try:
            self._enable_windows_shadow_style(hwnd)
            dwmapi = ctypes.windll.dwmapi
            hwnd_p = wintypes.HWND(hwnd)

            # Keep DWM non-client rendering enabled.  Disabling it can expose
            # the classic Win10 caption/buttons behind the frameless QML chrome.
            policy = ctypes.c_int(2)  # DWMNCRP_ENABLED
            try:
                dwmapi.DwmSetWindowAttribute(hwnd_p, 2, ctypes.byref(policy), ctypes.sizeof(policy))
            except Exception:
                pass

            class MARGINS(ctypes.Structure):
                _fields_ = [
                    ("cxLeftWidth", ctypes.c_int),
                    ("cxRightWidth", ctypes.c_int),
                    ("cyTopHeight", ctypes.c_int),
                    ("cyBottomHeight", ctypes.c_int),
                ]

            maximized = self._is_maximized_or_fullscreen(win)
            snapped = False
            try:
                snapped = str(self._settings.value_py(f"windows/{self._key(win)}/visibility", "")).startswith("snapped-") or self._looks_like_snapped_window(win, self._key(win))
            except Exception:
                snapped = False
            # Win10 uses the QML shadow because native shadows have square
            # corners. Win11 keeps the system shadow/corner pipeline.
            margins = MARGINS(0, 0, 0, 0) if use_custom_window_shadow() else MARGINS(1, 1, 1, 1)
            try:
                dwmapi.DwmExtendFrameIntoClientArea(hwnd_p, ctypes.byref(margins))
            except Exception:
                pass

            try:
                if maximized:
                    corner_pref = ctypes.c_int(1)  # DWMWCP_DONOTROUND
                elif is_windows_11_or_newer():
                    corner_pref = ctypes.c_int(0)  # DWMWCP_DEFAULT
                else:
                    corner_pref = ctypes.c_int(2)  # DWMWCP_ROUND when available
                dwmapi.DwmSetWindowAttribute(hwnd_p, 33, ctypes.byref(corner_pref), ctypes.sizeof(corner_pref))
            except Exception:
                pass

            try:
                border_none = ctypes.c_uint(0xFFFFFFFE)
                dwmapi.DwmSetWindowAttribute(hwnd_p, 34, ctypes.byref(border_none), ctypes.sizeof(border_none))
            except Exception:
                pass
        except Exception:
            return

    def _enable_windows_shadow_style(self, hwnd: int) -> None:
        try:
            user32 = ctypes.windll.user32
            GWL_STYLE = -16
            WS_THICKFRAME = 0x00040000
            WS_CAPTION = 0x00C00000
            WS_SYSMENU = 0x00080000
            WS_MINIMIZEBOX = 0x00020000
            WS_MAXIMIZEBOX = 0x00010000
            SWP_NOMOVE = 0x0002
            SWP_NOSIZE = 0x0001
            SWP_NOZORDER = 0x0004
            SWP_NOACTIVATE = 0x0010
            SWP_FRAMECHANGED = 0x0020
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
            hwnd_p = wintypes.HWND(hwnd)
            style = int(get_long(hwnd_p, GWL_STYLE))
            new_style = style | WS_THICKFRAME | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX
            if new_style != style:
                set_long(hwnd_p, GWL_STYLE, new_style)
                user32.SetWindowPos(hwnd_p, None, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        except Exception:
            pass
