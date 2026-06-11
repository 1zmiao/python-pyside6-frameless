from app.bridge.memory_tools import configure_process_allocator
from app.runtime_logging import flush_runtime_log, install_exception_logging, install_python_log_tee, write_runtime_log

install_python_log_tee()
install_exception_logging()

configure_process_allocator()

from app.main import main

if __name__ == "__main__":
    import os
    import sys

    exit_code = int(main())
    write_runtime_log(f"main returned exit_code={exit_code}")
    sys.stdout.flush()
    sys.stderr.flush()
    flush_runtime_log()
    if os.name == "nt" and os.environ.get("QROUNDEDFRAME_DISABLE_RUN_FAST_EXIT", "").strip().lower() not in {"1", "true", "yes"}:
        write_runtime_log(f"fast os._exit({exit_code})")
        flush_runtime_log()
        os._exit(exit_code)
    raise SystemExit(exit_code)
