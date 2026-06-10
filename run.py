from app.bridge.memory_tools import configure_process_allocator

configure_process_allocator()

from app.main import main

if __name__ == "__main__":
    import os
    import sys

    exit_code = int(main())
    sys.stdout.flush()
    sys.stderr.flush()
    if os.name == "nt" and os.environ.get("QROUNDEDFRAME_DISABLE_RUN_FAST_EXIT", "").strip().lower() not in {"1", "true", "yes"}:
        os._exit(exit_code)
    raise SystemExit(exit_code)
