# Native runtime prebuilt package

这个目录用于放置已经编译好的 `FramelessNative` Qt Quick 模块。运行程序的人不需要安装
CMake、Visual Studio、GCC 或了解 C++。

Python 启动时会按顺序查找：

```text
app/native/prebuilt/<platform>-<arch>-<py>-<qt>/qml
app/native/prebuilt/<platform>-<machine>/qml
app/native/prebuilt/current/qml
```

当前 Windows/Python 3.10/PySide6 6.11 的推荐目录名类似：

```text
app/native/prebuilt/win32-x64-py310-qt6.11/
  bin/
  qml/
    FramelessNative/
      qmldir
      FramelessNative.dll
```

`bin/` 用于放置 QWindowKit 或本模块依赖的 DLL；`qml/` 会被加入 QML import path。
如果没有匹配的预编译模块，程序会自动回退到旧的 Python 窗口实现。
