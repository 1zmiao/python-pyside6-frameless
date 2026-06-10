from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path


APP_NAME = "QRoundedFrame"

PYSIDE_EXCLUDES = [
    "PySide6.Qt3DAnimation",
    "PySide6.Qt3DCore",
    "PySide6.Qt3DExtras",
    "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic",
    "PySide6.Qt3DRender",
    "PySide6.QtBluetooth",
    "PySide6.QtCharts",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs",
    "PySide6.QtHelp",
    "PySide6.QtMultimedia",
    "PySide6.QtMultimediaWidgets",
    "PySide6.QtNetworkAuth",
    "PySide6.QtPdf",
    "PySide6.QtPdfWidgets",
    "PySide6.QtPositioning",
    "PySide6.QtQuick3D",
    "PySide6.QtRemoteObjects",
    "PySide6.QtScxml",
    "PySide6.QtSensors",
    "PySide6.QtSerialBus",
    "PySide6.QtSerialPort",
    "PySide6.QtSpatialAudio",
    "PySide6.QtStateMachine",
    "PySide6.QtTest",
    "PySide6.QtTextToSpeech",
    "PySide6.QtWebChannel",
    "PySide6.QtWebEngineCore",
    "PySide6.QtWebEngineQuick",
    "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebSockets",
    "PySide6.QtXml",
]

QT_FILE_PRUNE_PREFIXES = [
    "Qt63D",
    "Qt6Charts",
    "Qt6DataVisualization",
    "Qt6Graphs",
    "Qt6Location",
    "Qt6Multimedia",
    "Qt6Pdf",
    "Qt6Positioning",
    "Qt6Quick3D",
    "Qt6QuickParticles",
    "Qt6QuickTest",
    "Qt6RemoteObjects",
    "Qt6Scxml",
    "Qt6Sensors",
    "Qt6SpatialAudio",
    "Qt6StateMachine",
    "Qt6Test",
    "Qt6TextToSpeech",
    "Qt6VirtualKeyboard",
    "Qt6Web",
]

QT_FILE_PRUNE_NAMES = [
    "Qt6QuickControls2FluentWinUI3StyleImpl.dll",
    "Qt6QuickControls2Fusion.dll",
    "Qt6QuickControls2FusionStyleImpl.dll",
    "Qt6QuickControls2Imagine.dll",
    "Qt6QuickControls2ImagineStyleImpl.dll",
    "Qt6QuickControls2Material.dll",
    "Qt6QuickControls2MaterialStyleImpl.dll",
    "Qt6QuickControls2Universal.dll",
    "Qt6QuickControls2UniversalStyleImpl.dll",
]

QT_QML_PRUNE_DIRS = [
    "Qt3D",
    "QtCharts",
    "QtDataVisualization",
    "QtGraphs",
    "QtLocation",
    "QtMultimedia",
    "QtPdf",
    "QtPositioning",
    "QtQuick3D",
    "QtRemoteObjects",
    "QtScxml",
    "QtSensors",
    "QtTest",
    "QtTextToSpeech",
    "QtVirtualKeyboard",
    "QtWebChannel",
    "QtWebEngine",
    "QtWebSockets",
]

QT_CONTROL_STYLE_PRUNE_DIRS = [
    "FluentWinUI3",
    "Fusion",
    "Imagine",
    "Material",
    "Universal",
]


def run(cmd: list[str], cwd: Path) -> None:
    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=str(cwd), check=True)


def add_data_arg(source: Path, target: str) -> str:
    separator = ";" if sys.platform == "win32" else ":"
    return f"{source}{separator}{target}"


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)


def clean_release(release_dir: Path) -> None:
    for pattern in ("*.lib", "*.exp", "*.pdb", "*.pyc", "*.pyo"):
        for path in release_dir.rglob(pattern):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    for path in list(release_dir.rglob("__pycache__")):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)

    internal = release_dir / "_internal"
    runtime_assets = internal / "run"
    remove_tree(runtime_assets / "resources" / "examples")
    remove_tree(runtime_assets / "resources" / "fonts")
    remove_tree(release_dir / "user_data")
    prune_unused_qt(internal / "PySide6")


def prune_unused_qt(pyside_dir: Path) -> None:
    if not pyside_dir.exists():
        return

    for path in pyside_dir.iterdir():
        if not path.is_file():
            continue
        if path.name in QT_FILE_PRUNE_NAMES or any(path.name.startswith(prefix) for prefix in QT_FILE_PRUNE_PREFIXES):
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    qml_root = pyside_dir / "qml"
    for dirname in QT_QML_PRUNE_DIRS:
        remove_tree(qml_root / dirname)
    controls_root = qml_root / "QtQuick" / "Controls"
    for dirname in QT_CONTROL_STYLE_PRUNE_DIRS:
        remove_tree(controls_root / dirname)

    remove_tree(pyside_dir / "translations")


def package(root: Path, app_name: str, dist_dir: Path, work_dir: Path, clean: bool) -> Path:
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

    from app.native.runtime import _runtime_tag

    run([
        sys.executable,
        "scripts/check_native_window_integrity.py",
        "--require-prebuilt",
        "--summary",
        "--tag",
        _runtime_tag(),
    ], root)
    run([
        sys.executable,
        "-m",
        "py_compile",
        "app/main.py",
        "app/native/runtime.py",
        "app/bridge/util.py",
    ], root)

    if clean:
        remove_tree(dist_dir / app_name)
        remove_tree(work_dir)
        spec_file = root / "build" / f"{app_name}.spec"
        if spec_file.exists():
            spec_file.unlink()

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--windowed",
        "--name",
        app_name,
        "--distpath",
        str(dist_dir),
        "--workpath",
        str(work_dir),
        "--specpath",
        "build",
        "--icon",
        str(root / "resources" / "app_icon.ico"),
        "--add-data",
        add_data_arg(root / "qml", "run/qml"),
        "--add-data",
        add_data_arg(root / "resources" / "icons", "run/resources/icons"),
        "--add-data",
        add_data_arg(root / "resources" / "images", "run/resources/images"),
        "--add-data",
        add_data_arg(root / "resources" / "app_icon.ico", "run/resources"),
        "--add-data",
        add_data_arg(root / "app" / "native" / "prebuilt", "run/app/native/prebuilt"),
    ]
    for module in PYSIDE_EXCLUDES:
        cmd.extend(["--exclude-module", module])
    cmd.append("run.py")

    run(cmd, root)

    release_dir = dist_dir / app_name
    clean_release(release_dir)
    return release_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Package the PySide6/QML app.")
    parser.add_argument("--name", default=os.environ.get("APP_NAME", APP_NAME))
    parser.add_argument("--dist", default=os.environ.get("DIST_DIR", "dist"))
    parser.add_argument("--work", default=os.environ.get("WORK_DIR", "build/pyinstaller"))
    parser.add_argument("--no-clean", action="store_true", help="Do not delete previous package build output first.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    release_dir = package(
        root=root,
        app_name=args.name,
        dist_dir=(root / args.dist).resolve(),
        work_dir=(root / args.work).resolve(),
        clean=not args.no_clean,
    )
    executable = release_dir / (f"{args.name}.exe" if sys.platform == "win32" else args.name)
    print()
    print(f"Packaged: {executable}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
