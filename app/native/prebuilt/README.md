# Native runtime prebuilt

这个目录存放已经编译好的 `FramelessNative` Qt Quick 模块。普通运行用户不需要安装 CMake、Visual Studio、GCC，也不需要理解 C++。

当前仓库保留 Windows x64 / Python 3.10 / PySide6(Qt) 6.11 的两套预编译模块：

```text
win32-x64-py310-qt6.11-system  # Windows 11 等可信系统圆角/阴影路径
win32-x64-py310-qt6.11-custom  # Windows 10、虚拟机、Basic Display 等自定义圆角/阴影路径
```

Linux 编译后也放在同一个父目录下，例如：

```text
linux-x64-py310-qt6.11-system
linux-x64-py310-qt6.11-custom
```

Python 启动时会由 `app/native/runtime.py` 根据 `app/window_policy.py` 的平台策略选择合适目录，并把其中的 `qml/` 加入 QML import path。

运行必需文件包括：

```text
qmldir
FramelessNative.dll / libFramelessNative.so
FramelessNativeplugin.dll / libFramelessNativeplugin.so
FramelessNative.qmltypes
FramelessNative_qml_module_dir_map.qrc
FramelessNative_qml_module_dir_map_rc.py
```

`.lib`、`.exp` 等链接产物不是普通运行必需文件，仓库默认不保留。

重新编译入口：

```bat
scripts\build_windows.bat
```

```bash
bash scripts/build_linux.sh
```
