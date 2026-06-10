# Linux 窗口策略测试交接

这份文档用于在 Linux 虚拟机里测试 QRoundedFrame 的窗口行为，并把测试通过的桌面环境加入自定义无边框白名单。

## 当前策略

Windows 版已经稳定，Linux 目前默认走保守策略：

- Linux 默认使用系统标题栏和系统窗口行为。
- 不默认启用自定义无边框、外置阴影和圆角裁剪。
- 只有显式强制或命中白名单后，才启用 Linux custom chrome。

Windows 策略补充：

- Windows 10 默认走自定义圆角/外置阴影。
- Windows 11 默认信任系统圆角和系统阴影，即使运行在普通虚拟机里也不再仅凭 `vmware/virtualbox/hyper-v` 标记强制 custom。
- 如果 Win11 虚拟机确实没有系统圆角，可用 `FRAMELESS_WINDOWS_VM_CUSTOM_CHROME=1` 或 `FRAMELESS_FORCE_CUSTOM_CHROME=1` 强制测试自定义窗口。
- `Microsoft Basic Display`、Remote Display、Virtual Display 这类明显 fallback 显示环境仍会自动启用 custom。

相关代码在：

```text
app/window_policy.py
```

当前白名单入口：

```python
LINUX_CUSTOM_CHROME_WM_ALLOWLIST: set[str] = set()
```

默认空列表表示所有 Linux 桌面都先走系统窗口。后续某个窗口管理器测试通过后，只需要把 token 加进去，例如：

```python
LINUX_CUSTOM_CHROME_WM_ALLOWLIST: set[str] = {"xfwm4"}
```

不要先预设一堆桌面环境。建议“测试一个，加一个”。

## 建议测试顺序

优先测试这些组合：

```text
1. GNOME Wayland
   Debian/Ubuntu 默认路线。预期：保守回退系统标题栏。

2. GNOME on Xorg
   预期：先保守回退；可强制 custom 做对比。

3. XFCE / xfwm4
   最适合优先测试 Linux 自定义无边框。

4. Cinnamon / muffin
   Mint 相关，值得测试。

5. KDE Plasma X11 / kwin_x11
   用户多，但行为可能更复杂。
```

## 安装多个桌面环境

在 Debian/Ubuntu 系虚拟机中可以安装多个桌面环境，然后在登录界面选择会话。

```bash
sudo apt update
sudo apt install task-xfce-desktop
sudo apt install task-cinnamon-desktop
sudo apt install task-kde-desktop
sudo apt install task-mate-desktop
```

安装后注销，不是切换用户。在登录界面选择当前用户后，点齿轮或 session 菜单，选择：

```text
GNOME
GNOME on Xorg
Xfce Session
Cinnamon
Plasma
MATE
```

如果测试要求干净复现，最终最好单独准备虚拟机；快速测试阶段可以同一个虚拟机装多个桌面切换。

## 测试命令

普通运行并打印策略：

```bash
FRAMELESS_DEBUG_WINDOW_POLICY=1 python run.py
```

强制启用 Linux 自定义窗口测试：

```bash
FRAMELESS_FORCE_CUSTOM_CHROME=1 FRAMELESS_DEBUG_WINDOW_POLICY=1 python run.py
```

临时把某个 WM 当作白名单测试，不改代码：

```bash
FRAMELESS_LINUX_CUSTOM_CHROME_WM=xfwm4 FRAMELESS_DEBUG_WINDOW_POLICY=1 python run.py
```

多个 token：

```bash
FRAMELESS_LINUX_CUSTOM_CHROME_WM=xfwm4,muffin,kwin_x11 FRAMELESS_DEBUG_WINDOW_POLICY=1 python run.py
```

强制系统标题栏：

```bash
FRAMELESS_FORCE_SYSTEM_CHROME=1 FRAMELESS_DEBUG_WINDOW_POLICY=1 python run.py
```

## 需要记录的环境信息

每个测试组合都记录：

```bash
echo $XDG_SESSION_TYPE
echo $XDG_CURRENT_DESKTOP
echo $XDG_SESSION_DESKTOP
echo $DESKTOP_SESSION
echo $WINDOW_MANAGER
python - <<'PY'
from app.window_policy import current_window_policy
print(current_window_policy())
PY
```

如果 `python - <<'PY'` 在当前 shell 不方便，可改用：

```bash
python -c "from app.window_policy import current_window_policy; print(current_window_policy())"
```

## 测试项目

系统标题栏默认路径：

- 能启动。
- 主窗口能移动、缩放、最小化、最大化、关闭。
- 软件自定义标题栏区域作为内容正常显示，不应出现自绘按钮和系统按钮冲突。
- 切换主题不卡到不可接受。
- 右键菜单、滚轮、输入框正常。

强制 custom chrome 路径：

- 主窗口是否能拖动。
- 四边和四角是否能缩放。
- 左上角缩放时内容是否跳动。
- 贴边、最大化、复原是否符合当前桌面环境习惯。
- 阴影是否跟随窗口，不应作为独立窗口乱飞或盖到前面。
- Wayland 下如果出现透明度不支持、窗口位置不可控、阴影分离，直接记录为不适合 custom chrome。

## 通过标准

只有满足这些条件才加入白名单：

- 启动稳定，无 QML/native 崩溃。
- 拖动、缩放、最大化、复原稳定。
- 阴影不乱飞、不抢焦点、不挡点击。
- 不明显卡顿。
- 多屏或缩放比例变化下没有明显窗口错位。

如果只是不完美但可用，不建议加入默认白名单；保留为用户手动强制开启。

## 修改白名单

测试通过后修改：

```text
app/window_policy.py
```

例如 XFCE 通过：

```python
LINUX_CUSTOM_CHROME_WM_ALLOWLIST: set[str] = {"xfwm4"}
```

Cinnamon 也通过：

```python
LINUX_CUSTOM_CHROME_WM_ALLOWLIST: set[str] = {"xfwm4", "muffin"}
```

KDE X11 通过后再加：

```python
LINUX_CUSTOM_CHROME_WM_ALLOWLIST: set[str] = {"xfwm4", "muffin", "kwin_x11"}
```

注意：不要因为某个发行版通过就加发行版名。这里判断的是窗口管理器/桌面环境，不是 Debian、Ubuntu、Mint 本身。

## 编译 Linux native 模块

Linux native 编译入口：

```bash
bash scripts/build_linux.sh
```

如果 Qt 不在 PySide6 默认位置：

```bash
FRAMELESS_QT_PREFIX=/opt/Qt/6.11.1/gcc_64 bash scripts/build_linux.sh
```

预期输出目录和 Windows 同级：

```text
app/native/prebuilt/linux-x64-py310-qt6.11-system/qml/FramelessNative
app/native/prebuilt/linux-x64-py310-qt6.11-custom/qml/FramelessNative
```

当前仓库只有 Windows 预编译模块时，Linux 会回退到 QML/Python 路径。Linux custom chrome 要做严肃测试，建议先编译对应 Linux native 模块。

## 不要动的东西

除非明确要修 Windows，否则 Linux 测试过程中不要改这些稳定路径：

```text
app/windows_host.py
app/cpp/frameless_native/src/external_shadow_controller.cpp
app/cpp/frameless_native/src/native_window_agent.cpp
app/native/prebuilt/win32-x64-py310-qt6.11-custom
app/native/prebuilt/win32-x64-py310-qt6.11-system
```

Windows 当前行为、阴影和打包产物已经验证过，Linux 改动应尽量集中在：

```text
app/window_policy.py
scripts/build_linux.sh
Linux native prebuilt 输出目录
```
