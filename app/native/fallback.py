class NativeWindowHelper:
    """Pure Python fallback placeholder.

    Python-side fallback for optional native integrations. The C++ QML module
    now lives under app/cpp/frameless_native and is loaded through runtime.py.
    """

    def install_window(self, window_id: int, options: dict | None = None) -> bool:
        return False

    def set_always_on_top(self, window_id: int, enabled: bool) -> bool:
        return False

    def set_shadow_enabled(self, window_id: int, enabled: bool) -> bool:
        return False

    def set_corner_radius(self, window_id: int, radius: int) -> bool:
        return False

    def set_hit_test_margins(self, window_id: int, left: int, top: int, right: int, bottom: int) -> bool:
        return False
