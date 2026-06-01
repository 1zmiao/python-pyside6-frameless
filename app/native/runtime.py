from __future__ import annotations

import os
import platform
import sys
from pathlib import Path


def _runtime_tag() -> str:
    system = sys.platform
    machine = platform.machine().lower()
    if machine in {"amd64", "x86_64"}:
        arch = "x64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        arch = machine or "unknown"
    py = f"py{sys.version_info.major}{sys.version_info.minor}"
    try:
        from PySide6 import __version__ as pyside_version

        qt = "qt" + ".".join(pyside_version.split(".")[:2])
    except Exception:
        qt = "qt"
    return f"{system}-{arch}-{py}-{qt}"


def native_runtime_variant() -> str:
    override = os.environ.get("FRAMELESS_NATIVE_VARIANT", "").strip().lower()
    if override in {"system", "custom"}:
        return override
    try:
        from app.window_policy import current_window_policy

        policy = current_window_policy()
        return "custom" if policy.custom_chrome or policy.custom_shadow else "system"
    except Exception:
        return "system"


def native_import_candidates(project_root: Path) -> list[Path]:
    root = Path(project_root)
    cpp_root = root / "app" / "cpp" / "frameless_native"
    prebuilt_root = root / "app" / "native" / "prebuilt"
    runtime_tag = _runtime_tag()
    variant = native_runtime_variant()
    candidates: list[Path] = []
    override = os.environ.get("FRAMELESS_NATIVE_QML_DIR", "").strip()
    if override:
        override_path = Path(override)
        candidates.append(override_path if override_path.is_absolute() else root / override_path)
    candidates.extend([
        prebuilt_root / f"{runtime_tag}-{variant}" / "qml",
        prebuilt_root / runtime_tag / variant / "qml",
        prebuilt_root / f"current-{variant}" / "qml",
        cpp_root / f"build-{variant}" / "qml",
        cpp_root / f"build-{variant}" / "Release" / "qml",
        cpp_root / f"install-{variant}" / "qml",
    ])
    if os.environ.get("FRAMELESS_NATIVE_ALLOW_LEGACY_PREBUILT", "").strip().lower() in {"1", "true", "yes"}:
        candidates.extend([
            prebuilt_root / runtime_tag / "qml",
            prebuilt_root / f"{sys.platform}-{platform.machine().lower()}" / "qml",
            prebuilt_root / "current" / "qml",
            cpp_root / "build" / "qml",
            cpp_root / "build" / "Release" / "qml",
            cpp_root / "install" / "qml",
            # Backward-compatible lookup for older local builds created before the
            # C++ code was moved under app/cpp.
            root / "native" / "build" / "qml",
            root / "build" / "native" / "qml",
        ])
    return candidates


def native_runtime_available(project_root: Path) -> bool:
    if os.environ.get("FRAMELESS_FORCE_LEGACY_WINDOW", "").strip().lower() in {"1", "true", "yes"}:
        return False
    try:
        from app.window_policy import native_window_shell_preferred

        if not native_window_shell_preferred():
            return False
    except Exception:
        if os.environ.get("FRAMELESS_ENABLE_NATIVE_WINDOW", "").strip().lower() not in {"1", "true", "yes"}:
            return False
    for path in native_import_candidates(project_root):
        if (path / "FramelessNative" / "qmldir").exists():
            return True
    return False


def configure_native_runtime(engine, project_root: Path) -> bool:
    configured = False
    prebuilt_root = Path(project_root) / "app" / "native" / "prebuilt"
    runtime_tag = _runtime_tag()
    variant = native_runtime_variant()
    for path in native_import_candidates(project_root):
        if path.exists():
            engine.addImportPath(str(path))
            configured = True

    dll_dirs = [
        prebuilt_root / f"{runtime_tag}-{variant}" / "bin",
        prebuilt_root / runtime_tag / variant / "bin",
        prebuilt_root / f"current-{variant}" / "bin",
        Path(project_root) / "app" / "cpp" / "frameless_native" / f"build-{variant}" / "bin",
        Path(project_root) / "app" / "cpp" / "frameless_native" / f"build-{variant}" / "Release",
        Path(project_root) / "app" / "cpp" / "frameless_native" / f"install-{variant}" / "bin",
    ]
    if os.environ.get("FRAMELESS_NATIVE_ALLOW_LEGACY_PREBUILT", "").strip().lower() in {"1", "true", "yes"}:
        dll_dirs.extend([
            prebuilt_root / runtime_tag / "bin",
            prebuilt_root / f"{sys.platform}-{platform.machine().lower()}" / "bin",
            prebuilt_root / "current" / "bin",
            Path(project_root) / "app" / "cpp" / "frameless_native" / "build" / "bin",
            Path(project_root) / "app" / "cpp" / "frameless_native" / "build" / "Release",
            Path(project_root) / "app" / "cpp" / "frameless_native" / "install" / "bin",
        ])

    # Add every QML import candidate's FramelessNative dir so that the
    # plugin DLL loader can resolve FramelessNative.dll (its shared lib).
    for qml_candidate in native_import_candidates(project_root):
        fn_dir = qml_candidate / "FramelessNative"
        if fn_dir.exists():
            dll_dirs.insert(0, fn_dir)
            break
    if sys.platform == "win32":
        for dll_dir in dll_dirs:
            if dll_dir.exists():
                os.environ["PATH"] = f"{dll_dir}{os.pathsep}{os.environ.get('PATH', '')}"
                try:
                    os.add_dll_directory(str(dll_dir))
                except Exception:
                    pass
    return configured
