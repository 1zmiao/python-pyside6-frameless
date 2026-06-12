# Linux 窗口策略测试与交接说明

这份文档用于从 Windows 版本切到 Linux 版本时交接窗口行为、阴影、内存口径和编译事项。当前 Windows 版本已经告一段落；Linux 版本不要照搬 Windows 的窗口壳修补历史，要按 Linux 桌面环境逐项验证。

## 当前结论

- Windows 侧已经走稳定的 C++/QWindowKit 主窗口壳 + 外置 helper 阴影，不要为了 Linux 回头改 Windows 已稳定线路。
- Linux 默认仍走保守策略：优先系统窗口行为；只有明确测试通过的桌面/窗口管理器才启用 custom chrome。
- Linux 的自定义阴影问题和 Windows 不是一类问题。Windows 可通过 Win32 HWND 层级、DWM、SetWindowPos 等控制；Linux 受 X11/Wayland、窗口管理器、合成器策略影响更大。
- 如果 Linux custom chrome 仍使用外置阴影窗口，需要重点验证阴影层级、跨屏/出屏行为、缩放左上角时阴影右侧和底部抖动。

## 是否需要重新编译

需要。Windows 现在的预编译 native 模块不能直接给 Linux 用。

Linux native 编译入口：

```bash
bash scripts/build_linux.sh
```

如果 Qt 不在 PySide6 默认位置：

```bash
FRAMELESS_QT_PREFIX=/opt/Qt/6.11.1/gcc_64 bash scripts/build_linux.sh
```

期望输出目录：

```text
app/native/prebuilt/linux-x64-py310-qt6.11-system/qml/FramelessNative
app/native/prebuilt/linux-x64-py310-qt6.11-custom/qml/FramelessNative
```

编译后先跑：

```bash
python scripts/check_native_window_integrity.py --require-prebuilt --summary
```

如果只在 Linux 上调试 custom chrome，建议先强制启用测试，不要直接加入默认白名单：

```bash
FRAMELESS_FORCE_CUSTOM_CHROME=1 FRAMELESS_DEBUG_WINDOW_POLICY=1 python run.py
```

## Linux 内存显示口径

`app/memory_snapshot.py` 现在在 Linux 下优先读取 `/proc/self/smaps_rollup`：

- `rss`：进程驻留内存。
- `uss`：Unique Set Size，私有驻留内存，更接近“这个进程独占用了多少物理内存”。
- `pss`：Proportional Set Size，共享页按比例折算。
- `private`：Linux 下映射为 USS。
- `ws_private`：为了复用 Windows UI 字段，Linux 下也映射为 USS。

也就是说，更新页里显示的“当前私有驻留内存”在 Linux 上应理解为 USS。它不是 Windows 的 Working Set - Private，但用户感知上最接近。

Linux 运行前 `run.py` 会调用：

```python
configure_process_allocator()
```

Linux 侧会设置：

```text
QT_QUICK_BACKEND=software
mallopt(M_TRIM_THRESHOLD)
mallopt(M_MMAP_THRESHOLD)
mallopt(M_ARENA_MAX=2)
```

这条线是为了让 Linux 内存更容易回落，不要轻易删除。若要对比硬件渲染，需要单独记录内存和滚动/缩放流畅度。

## 当前 Linux 阴影遗留问题

之前 Linux 自定义阴影还残留这些问题：

1. 缩放左上角窗口时，窗口底部和右侧的阴影会抖动。
2. 阴影虽然在本软件窗口下面，但会被其他系统级窗口盖住。
3. 窗口移出屏幕外时，阴影被限制在屏幕内，不能跟随主窗口一起越界。

这些问题更像 Linux 外置阴影窗口的窗口管理器层级/约束问题，不是 QML 内容层问题。建议在 Linux 系统上修，不建议在 Windows 机器上盲改。

优先排查方向：

- X11 下检查 shadow helper 窗口是否设置为合适的 transient/override-redirect/type hint。
- 阴影窗口不要设置会被 WM 限制在 workarea 内的普通顶层窗口属性。
- 阴影应跟随目标窗口 frame geometry，而不是 client geometry。
- 缩放过程中不要靠 QML timer 追位置；优先接 native configure/geometry 事件。
- Wayland 下外置阴影窗口位置和层级通常不可可靠控制，若复现上述问题，建议该会话直接禁用 custom external shadow，回退系统窗口/系统阴影。

## 测试环境记录

每个 Linux 桌面都记录：

```bash
echo $XDG_SESSION_TYPE
echo $XDG_CURRENT_DESKTOP
echo $XDG_SESSION_DESKTOP
echo $DESKTOP_SESSION
echo $WINDOW_MANAGER
python -c "from app.window_policy import current_window_policy; print(current_window_policy())"
```

建议测试顺序：

1. GNOME Wayland：预期保守走系统窗口，不建议 custom external shadow。
2. GNOME on Xorg：可强制 custom 做对比，但不要默认启用。
3. XFCE / xfwm4：最适合优先验证 Linux custom chrome。
4. Cinnamon / muffin：可测。
5. KDE Plasma X11 / kwin_x11：用户多，但窗口规则复杂，必须单独验证。

## 白名单策略

默认白名单仍为空：

```python
LINUX_CUSTOM_CHROME_WM_ALLOWLIST: set[str] = set()
```

只在某个窗口管理器完整通过后再加入，例如：

```python
LINUX_CUSTOM_CHROME_WM_ALLOWLIST: set[str] = {"xfwm4"}
```

不要按发行版加白名单。判断对象应该是窗口管理器/会话类型，不是 Ubuntu、Debian、Mint。

## 必测项目

系统窗口默认路径：

- 主窗口启动、移动、缩放、最小化、最大化、关闭正常。
- 自绘标题栏内容不和系统标题栏按钮冲突。
- 主题切换不卡到不可接受。
- 右键菜单、滚动、输入框、任务列表正常。

强制 custom chrome 路径：

- 四边和四角缩放命中区正确。
- 左上角缩放时右侧/底部边界不漏底、不反复抖。
- 阴影跟随窗口，不抢焦点、不挡点击、不乱飞。
- 最大化、半屏、恢复符合当前桌面环境习惯。
- 窗口移出屏幕时，阴影和主窗口一致，不被强行裁在屏幕内。
- 其他应用窗口覆盖时，阴影层级不应该跑到不合理的位置。

## 通过标准

只有满足这些条件才建议默认启用 Linux custom chrome：

- 启动稳定，无 QML/native 崩溃。
- 移动、缩放、最大化、恢复稳定。
- 阴影不乱飞、不抢焦点、不挡点击。
- 左上角缩放时阴影和窗口边界可接受。
- 多屏、不同缩放比例下无明显错位。

如果只是“能用但不完美”，不要加入默认白名单，保留为环境变量强制启用。

## 不要动的 Windows 稳定路径

Linux 调试时不要顺手改这些 Windows 稳定文件，除非明确要修 Windows：

```text
app/windows_host.py
app/cpp/frameless_native/src/external_shadow_controller.cpp
app/cpp/frameless_native/src/native_window_agent.cpp
app/native/prebuilt/win32-x64-py310-qt6.11-custom
app/native/prebuilt/win32-x64-py310-qt6.11-system
```

Linux 优先改动范围：

```text
app/window_policy.py
scripts/build_linux.sh
app/cpp/frameless_native/src/linux 或跨平台但经 Linux 实测确认的 native 代码
app/native/prebuilt/linux-x64-py310-qt6.11-*
```

## 优化理念交接

- 不要用高频 timer 追窗口或阴影位置。
- 不要为了阴影修复去破坏主窗口内容层。
- Linux 下能用系统窗口行为就优先系统窗口行为。
- 外置阴影必须跟随 native geometry 事件，不能依赖 QML 下一帧。
- 内存显示优先看 USS；RSS 会包含共享库和 Qt 显存相关驻留，不能直接和 Windows Working Set - Private 等价。
- 列表大数据继续使用模型虚拟化，不要用 Repeater 展开大量条目。
- 视觉优化和内存优化要保留可回退开关，避免低内存策略影响默认视觉效果。
