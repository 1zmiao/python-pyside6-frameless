# Build script notes

Use the project-root `b.bat` as the canonical Windows build entry for the native QWindowKit module.

Before building, `b.bat` runs:

```bat
python scripts\check_native_window_integrity.py
```

After building both variants, `b.bat` runs:

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

The Python runtime chooses the `system` variant for trusted Win11 system corners/shadows and the `custom` variant for Win10/VM/custom chrome fallback. If the matching variant is missing, the application falls back to the legacy Python/QML window path. The older unqualified prebuilt directory is forbidden by the integrity check.

Linux builds should use the same CMake project under `app/cpp/frameless_native` and publish the resulting QML module under the matching runtime tag in `app/native/prebuilt/`.