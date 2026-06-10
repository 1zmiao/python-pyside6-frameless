from __future__ import annotations

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QGuiApplication


class ThemeController(QObject):
    modeChanging = Signal(str, str)
    modeChanged = Signal(str)
    primaryColorChanged = Signal(str)
    primaryColorCommitted = Signal(str)
    fontScaleChanged = Signal(float)
    showColorButtonChanged = Signal(bool)
    rippleOriginChanged = Signal(float, float)

    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self._settings = settings
        self._mode = str(settings.value_py("theme/mode", "dark"))
        # Separate theme colors for light/dark modes.  Old projects that only
        # have theme/primaryColor are migrated lazily into the light theme.
        legacy = str(settings.value_py("theme/primaryColor", "#5886D9")).upper()
        self._light_primary = str(settings.value_py("theme/lightPrimaryColor", "#5886D9")).upper()
        self._dark_primary = str(settings.value_py("theme/darkPrimaryColor", "#3A3FAC")).upper()
        self._font_scale = self._clamp_font_scale(settings.value_py("ui/fontScale", 1.0))
        self._show_color_button = bool(settings.value_py("ui/showColorButton", True))
        self._ripple_x = 0.5
        self._ripple_y = 0.5
        self._pending_preview_primary: str | None = None
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(8)
        self._preview_timer.timeout.connect(self._flush_preview_primary_color)

    @Property(str, notify=modeChanged)
    def mode(self) -> str:
        return self._mode

    @Property(str, notify=primaryColorChanged)
    def primaryColor(self) -> str:
        return self._dark_primary if self._mode == "dark" else self._light_primary

    @Slot(str, result=str)
    def primaryColorForMode(self, mode: str) -> str:
        return self._dark_primary if str(mode) == "dark" else self._light_primary

    @Property(float, notify=fontScaleChanged)
    def fontScale(self) -> float:
        return self._font_scale

    @Property(bool, notify=showColorButtonChanged)
    def showColorButton(self) -> bool:
        return self._show_color_button

    @Property(float, notify=rippleOriginChanged)
    def rippleX(self) -> float:
        return self._ripple_x

    @Property(float, notify=rippleOriginChanged)
    def rippleY(self) -> float:
        return self._ripple_y

    @Slot(str)
    def setMode(self, mode: str) -> None:
        if mode not in {"light", "dark"}:
            return
        if mode == self._mode:
            return
        self.modeChanging.emit(self._mode, mode)
        self._mode = mode
        self._settings.set_value_py("theme/mode", mode)
        self.modeChanged.emit(mode)
        # The exposed primaryColor changes when the mode changes because light
        # and dark palettes have independent user-selected colors.
        self.primaryColorChanged.emit(self.primaryColor)

    @Slot(result=str)
    def toggleMode(self) -> str:
        next_mode = "light" if self._mode == "dark" else "dark"
        self.setMode(next_mode)
        return next_mode

    @Slot(str)
    def setPrimaryColor(self, color: str) -> None:
        qcolor = QColor(color)
        if not qcolor.isValid():
            return
        normalized = qcolor.name(QColor.NameFormat.HexRgb).upper()
        self._pending_preview_primary = None
        if self._preview_timer.isActive():
            self._preview_timer.stop()
        self._set_primary_memory(normalized)
        if self._mode == "dark":
            self._settings.set_value_py("theme/darkPrimaryColor", normalized)
        else:
            self._settings.set_value_py("theme/lightPrimaryColor", normalized)
        # Keep legacy key updated for older code/users that inspect settings.json.
        self._settings.set_value_py("theme/primaryColor", normalized)
        self.primaryColorCommitted.emit(normalized)

    @Slot(str)
    def previewPrimaryColor(self, color: str) -> None:
        qcolor = QColor(color)
        if not qcolor.isValid():
            return
        normalized = qcolor.name(QColor.NameFormat.HexRgb).upper()
        self._pending_preview_primary = normalized
        if not self._preview_timer.isActive():
            self._preview_timer.start()

    def _flush_preview_primary_color(self) -> None:
        normalized = self._pending_preview_primary
        self._pending_preview_primary = None
        if normalized:
            self._set_primary_memory(normalized)

    def _set_primary_memory(self, normalized: str) -> None:
        if self._mode == "dark":
            if normalized == self._dark_primary.upper():
                return
            self._dark_primary = normalized
        else:
            if normalized == self._light_primary.upper():
                return
            self._light_primary = normalized
        self.primaryColorChanged.emit(normalized)

    @Slot(float, float)
    def setRippleOrigin(self, x: float, y: float) -> None:
        try:
            nx = float(x)
            ny = float(y)
        except Exception:
            nx, ny = 0.5, 0.5
        self._ripple_x = nx
        self._ripple_y = ny
        self.rippleOriginChanged.emit(nx, ny)

    @Slot(bool)
    def setShowColorButton(self, enabled: bool) -> None:
        value = bool(enabled)
        if value == self._show_color_button:
            return
        self._show_color_button = value
        self._settings.set_value_py("ui/showColorButton", value)
        self.showColorButtonChanged.emit(value)

    @Slot(float)
    def setFontScale(self, scale: float) -> None:
        value = self._clamp_font_scale(scale)
        if abs(value - self._font_scale) < 0.001:
            return
        self._font_scale = value
        self._settings.set_value_py("ui/fontScale", round(value, 3))
        self.fontScaleChanged.emit(value)

    @Slot(result=float)
    def increaseFontScale(self) -> float:
        self.setFontScale(self._font_scale + 0.05)
        return self._font_scale

    @Slot(result=float)
    def decreaseFontScale(self) -> float:
        self.setFontScale(self._font_scale - 0.05)
        return self._font_scale

    @Slot()
    def resetFontScale(self) -> None:
        self.setFontScale(1.0)

    def _clamp_font_scale(self, scale) -> float:
        try:
            value = float(scale)
        except Exception:
            value = 1.0
        return max(0.85, min(1.35, value))

    @Slot(str, result=bool)
    def copyText(self, text: str) -> bool:
        return self.copyToClipboard(text)

    @Slot(str, result=bool)
    def copyToClipboard(self, text: str) -> bool:
        clipboard = QGuiApplication.clipboard()
        if clipboard is None:
            return False
        clipboard.setText(str(text))
        return True
