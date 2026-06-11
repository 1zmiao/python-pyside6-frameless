from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path
from typing import TextIO

_LOG_FILE: TextIO | None = None
_ORIGINAL_STDOUT = sys.stdout
_ORIGINAL_STDERR = sys.stderr
_QT_HANDLER_INSTALLED = False


class _TeeStream:
    def __init__(self, original: TextIO, log_file: TextIO, label: str) -> None:
        self._original = original
        self._log_file = log_file
        self._label = label

    @property
    def encoding(self):
        return getattr(self._original, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._original, "errors", "replace")

    def write(self, text: str) -> int:
        try:
            written = self._original.write(text)
        except Exception:
            written = len(text)
        try:
            self._log_file.write(text)
            self._log_file.flush()
        except Exception:
            pass
        return written

    def flush(self) -> None:
        try:
            self._original.flush()
        except Exception:
            pass
        try:
            self._log_file.flush()
        except Exception:
            pass

    def isatty(self) -> bool:
        try:
            return bool(self._original.isatty())
        except Exception:
            return False

    def fileno(self) -> int:
        return self._original.fileno()

    def __getattr__(self, name: str):
        return getattr(self._original, name)


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def runtime_log_path() -> Path:
    return _project_root() / "user_data" / "logs" / "runtime_latest.log"


def install_python_log_tee() -> Path:
    global _LOG_FILE
    if _LOG_FILE is not None:
        return runtime_log_path()
    log_path = runtime_log_path()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    _LOG_FILE = log_path.open("w", encoding="utf-8", buffering=1)
    sys.stdout = _TeeStream(_ORIGINAL_STDOUT, _LOG_FILE, "stdout")  # type: ignore[assignment]
    sys.stderr = _TeeStream(_ORIGINAL_STDERR, _LOG_FILE, "stderr")  # type: ignore[assignment]
    write_runtime_log("runtime log opened")
    write_runtime_log(f"python={sys.executable}")
    write_runtime_log(f"cwd={Path.cwd()}")
    write_runtime_log(f"argv={sys.argv!r}")
    for name in [
        "PYTHONPATH",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "QT_QPA_PLATFORM",
        "QT_LOGGING_RULES",
        "FRAMELESS_NATIVE_VARIANT",
        "QROUNDEDFRAME_DISABLE_QWINDOWKIT_MAIN_SHELL",
        "QROUNDEDFRAME_DISABLE_RUN_FAST_EXIT",
    ]:
        value = os.environ.get(name)
        if value:
            write_runtime_log(f"env {name}={value}")
    return log_path


def write_runtime_log(message: str) -> None:
    if _LOG_FILE is None:
        return
    try:
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        _LOG_FILE.write(f"[{stamp}] {message}\n")
        _LOG_FILE.flush()
    except Exception:
        pass


def install_exception_logging() -> None:
    original_excepthook = sys.excepthook

    def excepthook(exc_type, exc, tb):
        write_runtime_log("unhandled Python exception:")
        if _LOG_FILE is not None:
            traceback.print_exception(exc_type, exc, tb, file=_LOG_FILE)
            _LOG_FILE.flush()
        original_excepthook(exc_type, exc, tb)

    sys.excepthook = excepthook


def install_qt_message_logging() -> None:
    global _QT_HANDLER_INSTALLED
    if _QT_HANDLER_INSTALLED:
        return
    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except Exception as exc:
        write_runtime_log(f"qt message handler unavailable: {exc!r}")
        return

    def handler(mode, context, message):
        try:
            if mode == QtMsgType.QtDebugMsg:
                level = "qt-debug"
            elif mode == QtMsgType.QtInfoMsg:
                level = "qt-info"
            elif mode == QtMsgType.QtWarningMsg:
                level = "qt-warning"
            elif mode == QtMsgType.QtCriticalMsg:
                level = "qt-critical"
            elif mode == QtMsgType.QtFatalMsg:
                level = "qt-fatal"
            else:
                level = "qt-message"
            location = ""
            try:
                if context and context.file:
                    location = f" ({context.file}:{context.line})"
            except Exception:
                location = ""
            write_runtime_log(f"{level}{location}: {message}")
        except Exception:
            pass
        try:
            print(message, file=_ORIGINAL_STDERR)
        except Exception:
            pass

    qInstallMessageHandler(handler)
    _QT_HANDLER_INSTALLED = True
    write_runtime_log("qt message handler installed")


def flush_runtime_log() -> None:
    try:
        sys.stdout.flush()
    except Exception:
        pass
    try:
        sys.stderr.flush()
    except Exception:
        pass
    try:
        if _LOG_FILE is not None:
            _LOG_FILE.flush()
    except Exception:
        pass
