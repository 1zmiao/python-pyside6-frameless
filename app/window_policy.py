from __future__ import annotations

import os
import platform
import sys
import ctypes
from dataclasses import dataclass

from app.windows_compat import is_windows_11_or_newer


TRUE_VALUES = {"1", "true", "yes", "on"}
FALSE_VALUES = {"0", "false", "no", "off"}


@dataclass(frozen=True)
class WindowAppearancePolicy:
    platform: str
    session_type: str
    desktop: str
    wm_name: str
    custom_chrome: bool
    custom_shadow: bool
    external_shadow_supported: bool
    native_shell_preferred: bool
    shadow_policy: str
    corner_policy: str
    reason: str


def _env_text(name: str) -> str:
    return os.environ.get(name, "").strip()


def _env_bool(name: str) -> bool | None:
    value = _env_text(name).lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    return None


def _linux_session_type() -> str:
    session = _env_text("XDG_SESSION_TYPE").lower()
    if session:
        return session
    if _env_text("WAYLAND_DISPLAY"):
        return "wayland"
    if _env_text("DISPLAY"):
        return "x11"
    return ""


def _linux_desktop() -> str:
    values = [
        _env_text("XDG_CURRENT_DESKTOP"),
        _env_text("XDG_SESSION_DESKTOP"),
        _env_text("DESKTOP_SESSION"),
    ]
    return ";".join(v for v in values if v).lower()


def _linux_wm_name() -> str:
    values = [
        _env_text("FRAMELESS_LINUX_WM"),
        _env_text("WINDOW_MANAGER"),
        _env_text("XDG_CURRENT_DESKTOP"),
    ]
    return ";".join(v for v in values if v).lower()


def _windows_display_fallback_needed() -> bool:
    override = _env_bool("FRAMELESS_ASSUME_SYSTEM_CORNERS")
    if override is not None:
        return not override
    if sys.platform != "win32":
        return False
    try:
        class DISPLAY_DEVICEW(ctypes.Structure):
            _fields_ = [
                ("cb", ctypes.c_ulong),
                ("DeviceName", ctypes.c_wchar * 32),
                ("DeviceString", ctypes.c_wchar * 128),
                ("StateFlags", ctypes.c_ulong),
                ("DeviceID", ctypes.c_wchar * 128),
                ("DeviceKey", ctypes.c_wchar * 128),
            ]

        user32 = ctypes.windll.user32
        texts: list[str] = []
        index = 0
        while index < 16:
            device = DISPLAY_DEVICEW()
            device.cb = ctypes.sizeof(DISPLAY_DEVICEW)
            if not user32.EnumDisplayDevicesW(None, index, ctypes.byref(device), 0):
                break
            texts.extend([device.DeviceName, device.DeviceString, device.DeviceID])
            index += 1
        joined = " ".join(t for t in texts if t).lower()
        fallback_markers = (
            "microsoft basic display",
            "microsoft remote display",
            "remote display",
            "vmware",
            "virtualbox",
            "virtual display",
            "hyper-v",
            "parallels",
            "virtio",
            "qxl",
        )
        return any(marker in joined for marker in fallback_markers)
    except Exception:
        return False


def _linux_system_corners_trusted(desktop: str, wm_name: str) -> bool:
    override = _env_bool("FRAMELESS_ASSUME_SYSTEM_CORNERS")
    if override is not None:
        return override

    # Linux decoration themes are too variable to trust by name. A desktop can
    # provide top rounded decoration while leaving client/content bottom corners
    # square, so system corners are trusted only through an explicit override.
    return False


def current_window_policy() -> WindowAppearancePolicy:
    force_native = _env_bool("FRAMELESS_ENABLE_NATIVE_WINDOW") is True
    force_legacy = _env_bool("FRAMELESS_FORCE_LEGACY_WINDOW") is True
    force_custom = _env_bool("FRAMELESS_FORCE_CUSTOM_CHROME") is True
    force_system = _env_bool("FRAMELESS_FORCE_SYSTEM_CHROME") is True

    if sys.platform == "win32":
        is_win11 = is_windows_11_or_newer()
        display_fallback = _windows_display_fallback_needed()
        custom_chrome = force_custom or ((not is_win11 or display_fallback) and not force_system)
        if force_system:
            custom_chrome = False
        custom_shadow = custom_chrome
        native_shell = False if force_legacy else True
        reason = "Windows 11+ system chrome trusted"
        if force_system:
            reason = "System chrome forced by environment"
        elif display_fallback:
            reason = "Windows display fallback custom chrome"
        elif custom_chrome:
            reason = "Windows fallback custom chrome"
        return WindowAppearancePolicy(
            platform="windows",
            session_type="",
            desktop="windows",
            wm_name=f"windows-build-{platform.version()}",
            custom_chrome=custom_chrome,
            custom_shadow=custom_shadow,
            external_shadow_supported=custom_shadow,
            native_shell_preferred=native_shell,
            shadow_policy="custom-external" if custom_shadow else "system",
            corner_policy="rounded" if custom_chrome else "auto",
            reason=reason,
        )

    if sys.platform.startswith("linux"):
        session = _linux_session_type()
        desktop = _linux_desktop()
        wm_name = _linux_wm_name()
        trusted = _linux_system_corners_trusted(desktop, wm_name)
        custom_chrome = force_custom or (not trusted and not force_system)
        if force_system:
            custom_chrome = False
        external_shadow = custom_chrome and session != "wayland"
        custom_shadow = custom_chrome
        native_shell = False if force_legacy else (force_native or custom_chrome)
        return WindowAppearancePolicy(
            platform="linux",
            session_type=session,
            desktop=desktop,
            wm_name=wm_name,
            custom_chrome=custom_chrome,
            custom_shadow=custom_shadow,
            external_shadow_supported=external_shadow,
            native_shell_preferred=native_shell,
            shadow_policy="custom-external" if external_shadow else ("none" if custom_chrome else "system"),
            corner_policy="rounded" if custom_chrome else "auto",
            reason="Linux system four-corner rounding not trusted" if custom_chrome else "Linux system corners explicitly trusted",
        )

    custom_chrome = force_custom and not force_system
    native_shell = False if force_legacy else (force_native or custom_chrome)
    return WindowAppearancePolicy(
        platform=sys.platform,
        session_type="",
        desktop="",
        wm_name="",
        custom_chrome=custom_chrome,
        custom_shadow=custom_chrome,
        external_shadow_supported=False,
        native_shell_preferred=native_shell,
        shadow_policy="none" if custom_chrome else "system",
        corner_policy="rounded" if custom_chrome else "auto",
        reason="Unsupported platform fallback",
    )


def use_custom_window_chrome() -> bool:
    return current_window_policy().custom_chrome


def use_custom_window_shadow() -> bool:
    return current_window_policy().custom_shadow


def external_shadow_supported() -> bool:
    return current_window_policy().external_shadow_supported


def native_window_shell_preferred() -> bool:
    return current_window_policy().native_shell_preferred
