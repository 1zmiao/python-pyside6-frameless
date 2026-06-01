import QtQuick
import "core" as Core
import "window"
import "layout"

AppWindow {
    id: win
    windowKey: "main"
    bridge: App
    title: Core.AppInfo.windowTitle
    width: 1080
    height: 700
    minimumWidth: 640
    minimumHeight: 420

    leftMenus: Core.AppInfo.mainMenus

    MainWindowContent {
        anchors.fill: parent
        windowObject: win
    }
}
