from __future__ import annotations

import ctypes
import gc
import os
import sys


def configure_process_allocator() -> None:
    if sys.platform == "win32":
        if os.environ.get("QROUNDEDFRAME_DISABLE_RESIZE_FAST_PRESENT", "").strip().lower() not in {"1", "true", "yes", "on"}:
            os.environ.setdefault("QSG_RHI_BACKEND", "d3d11")
            os.environ.setdefault("QSG_NO_VSYNC", "1")
            os.environ.setdefault("QT_QPA_UPDATE_IDLE_TIME", "0")
            os.environ.setdefault("QT_QPA_DISABLE_REDIRECTION_SURFACE", "1")
        if os.environ.get("QROUNDEDFRAME_FORCE_SOFTWARE_QUICK", "").strip().lower() in {"1", "true", "yes"}:
            os.environ.setdefault("QT_QUICK_BACKEND", "software")
    if sys.platform.startswith("linux"):
        os.environ.setdefault("QT_QUICK_BACKEND", "software")
    if os.name != "posix":
        return
    try:
        libc = ctypes.CDLL(None)
        if not hasattr(libc, "mallopt"):
            return
        m_trim_threshold = -1
        m_mmap_threshold = -3
        m_arena_max = -8
        libc.mallopt(m_trim_threshold, 128 * 1024)
        libc.mallopt(m_mmap_threshold, 128 * 1024)
        libc.mallopt(m_arena_max, 2)
    except Exception:
        pass


def trim_process_memory(engine=None, *, collect_qml: bool = False, empty_working_set: bool = False) -> None:
    if collect_qml and engine is not None:
        try:
            engine.collectGarbage()
        except Exception:
            pass
    gc.collect()
    if sys.platform == "win32" and empty_working_set and os.environ.get("QROUNDEDFRAME_ALLOW_WORKING_SET_TRIM", "").strip().lower() in {"1", "true", "yes"}:
        try:
            kernel32 = ctypes.windll.kernel32
            psapi = ctypes.windll.psapi
            handle = kernel32.GetCurrentProcess()
            try:
                psapi.EmptyWorkingSet(handle)
            except Exception:
                pass
            try:
                kernel32.SetProcessWorkingSetSize.argtypes = [
                    ctypes.c_void_p,
                    ctypes.c_size_t,
                    ctypes.c_size_t,
                ]
                kernel32.SetProcessWorkingSetSize.restype = ctypes.c_bool
                kernel32.SetProcessWorkingSetSize(
                    handle,
                    ctypes.c_size_t(-1).value,
                    ctypes.c_size_t(-1).value,
                )
            except Exception:
                pass
        except Exception:
            pass
    elif os.name == "posix":
        try:
            libc = ctypes.CDLL(None)
            if hasattr(libc, "malloc_trim"):
                libc.malloc_trim(0)
        except Exception:
            pass
