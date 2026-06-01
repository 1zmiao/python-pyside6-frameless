pragma Singleton
import QtQuick

QtObject {
    readonly property string windowTitle: "QML无边框窗口模板"
    readonly property var mainMenus: [
        { "text": "设置", "action": "settings" },
        { "text": "工具", "action": "tools" },
        { "text": "更新", "action": "update" },
        { "text": "关于", "action": "about" }
    ]
}
