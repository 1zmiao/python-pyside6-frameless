# Native window layer

This directory contains the optional C++ window layer used by `qml/window/AppWindow.qml`.

Build it before testing the QWindowKit path. On Windows, use the project-root
`b.bat`; it builds two variants:

```text
win32-x64-py310-qt6.11-system  -> QWindowKit Windows system borders enabled
win32-x64-py310-qt6.11-custom  -> QWindowKit Windows system borders disabled
```

or on Linux:

```bash
./scripts/build_native_linux.sh
```

The Python launcher selects the variant through `app/native/runtime.py`. Set
`FRAMELESS_FORCE_LEGACY_WINDOW=1` to force the legacy Python/QML fallback.

The real top-level window geometry is content-only. On Windows 10 or virtual/basic display sessions, custom shadow pixels are drawn by a transparent helper window instead of being embedded inside the main HWND.

Responsibility split:

- QWindowKit owns native frameless behavior: hit-test, resize, drag, snap, maximize/restore, and system button roles.
- `NativeWindowAgent` is only a thin QML-facing wrapper around `QWK::QuickWindowAgent`.
- `ExternalShadowController` is project-specific glue for custom shadow helper windows. It must not implement native resize/snap/titlebar behavior.
- Python decides the platform policy in `app/window_policy.py`. Rebuilding the C++ module does not change that policy.

Platform policy summary:

- Windows 11+ keeps the system path by default and should load the `system` variant.
- Windows 10 and virtual/basic display fallback use custom chrome and custom external shadow.
- Linux is conservative: unless `FRAMELESS_ASSUME_SYSTEM_CORNERS=1` or `FRAMELESS_FORCE_SYSTEM_CHROME=1` is set, the app assumes system decorations do not guarantee all four rounded corners and uses custom chrome.
- Linux/X11 may use the external shadow helper. Linux/Wayland keeps custom rounded chrome but does not assume external helper shadows can be synchronized behind a window on every compositor.
