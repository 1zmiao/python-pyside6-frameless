import QtQuick
import QtQuick.Window
import "."

AppWindow {
    id: child
    bridge: App
    autoRestoreWindowState: false
    autoShow: false
    showNavToggle: false
    title: pageTitle
    width: 760
    height: 520
    minimumWidth: 520
    minimumHeight: 360

    property var parentWindow: null
    property string pageSource: ""
    property string pageTitle: "子窗口"

    modality: Qt.NonModal

    Loader {
        anchors.fill: parent
        asynchronous: true
        source: child.pageSource
    }

    function applyParentWindow() {
        if (parentWindow !== null && parentWindow !== undefined) {
            x = parentWindow.x + 80
            y = parentWindow.y + 80
        }
    }

    onParentWindowChanged: applyParentWindow()
    Component.onCompleted: applyParentWindow()
}
