# Build script notes

Use `scripts/build_windows.bat` as the only Windows build entry for the native QWindowKit module. Linux uses `scripts/build_linux.sh`.

Packaging entry points:

```text
python scripts/package_app.py
```

The packaging script builds a PyInstaller one-dir release under `dist/QRoundedFrame/`.
They copy only runtime assets: QML, active icons/images, tray icon, and native prebuilt modules.
README screenshots, bundled font experiments, user data, logs, and native build trees are not included.

Before building, the Windows build runs:

```bat
python scripts\check_native_window_integrity.py
```

After building both variants, the Windows build runs:

```bat
python scripts\check_native_window_integrity.py --require-prebuilt --summary
```

Do not bypass these checks. They block the recurring failure modes:

- loading stale or legacy native DLLs
- reintroducing `QEvent::Expose` DWM reapplication
- forcing `SWP_FRAMECHANGED` or Win32 style rewrites on the main HWND
- enabling QML `ShadowWindow` on the Windows native external-shadow path
- missing or stale `system`/`custom` prebuilt outputs

Canonical Windows output:

```text
app/native/prebuilt/win32-x64-py310-qt6.11-system/qml/FramelessNative
app/native/prebuilt/win32-x64-py310-qt6.11-custom/qml/FramelessNative
```

Canonical Linux output is in the same parent directory:

```text
app/native/prebuilt/linux-x64-py310-qt6.11-system/qml/FramelessNative
app/native/prebuilt/linux-x64-py310-qt6.11-custom/qml/FramelessNative
```

The Python runtime chooses the `system` variant for trusted Win11 system corners/shadows and the `custom` variant for Win10/VM/custom chrome fallback. If the matching variant is missing, the application falls back to the legacy Python/QML window path. The older unqualified prebuilt directory is forbidden by the integrity check.

Linux builds use the same CMake project under `app/cpp/frameless_native` and publish the resulting QML module under the matching runtime tag in `app/native/prebuilt/`.

On Linux, run:

```bash
bash scripts/build_linux.sh
FRAMELESS_DEBUG_WINDOW_POLICY=1 python run.py
```

If Qt is installed outside the active PySide6 wheel, provide its Qt prefix:

```bash
FRAMELESS_QT_PREFIX=/opt/Qt/6.11.1/gcc_64 bash scripts/build_linux.sh
```

Expected output names follow the runtime tag and stay beside the Windows builds, for example:

```text
app/native/prebuilt/linux-x64-py310-qt6.11-custom/qml/FramelessNative
app/native/prebuilt/linux-x64-py310-qt6.11-system/qml/FramelessNative
```

Linux defaults to the conservative system-titlebar path. Debian, Ubuntu, Mint, and other unverified desktops should keep this default until the exact desktop/session/driver combination has been tested. To force custom chrome for testing:

```bash
FRAMELESS_FORCE_CUSTOM_CHROME=1 FRAMELESS_DEBUG_WINDOW_POLICY=1 python run.py
```

Linux without the native module, or Linux running in conservative system-titlebar mode, is not equivalent to the Windows QWindowKit/custom-shadow path.
