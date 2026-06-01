import QtQuick
import "../core" as Core
import "../controls"

Item {
    id: root

    property var windowObject

    Row {
        id: mainRow
        anchors.fill: parent

        ResizableSideNav {
            id: sideNav
            height: parent.height
            width: (typeof App !== "undefined" && App && App.settings)
                   ? Math.max(0, Math.min(App.settings.valueOr("layout/navWidth", Core.Theme.metrics.navWidthDefault), Core.Theme.metrics.navWidthMax))
                   : Core.Theme.metrics.navWidthDefault
            cornerRadius: root.windowObject ? root.windowObject.cornerRadius : Core.Theme.radius.window
            onCurrentPageChanged: pageHost.showPage(currentPage)
        }

        PageHost {
            id: pageHost
            width: parent.width - sideNav.width
            height: parent.height
        }

        TapHandler {
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            onTapped: if (trayMenu.visible) trayMenu.closeMenu()
        }
    }

    Binding {
        target: root.windowObject ? root.windowObject.titleBar : null
        property: "navHidden"
        value: sideNav.width === 0
    }

    Connections {
        target: root.windowObject ? root.windowObject.titleBar : null
        function onActivateRequested() {
            if (trayMenu.visible)
                trayMenu.closeMenu()
        }
        function onToggleNavRequested() {
            sideNav.toggle()
        }
        function onMenuActionRequested(action, kind) {
            if (kind === "page") {
                sideNav.restore()
                sideNav.currentPage = action
            } else if (typeof App !== "undefined" && App && App.dialogs) {
                App.dialogs.openChild(root.windowObject, action, ({}))
            }
        }
    }

    TrayMenuWindow { id: trayMenu }

    MouseArea {
        anchors.fill: parent
        z: 999999
        visible: trayMenu.visible
        enabled: visible
        acceptedButtons: Qt.LeftButton | Qt.RightButton
        onPressed: function(mouse) {
            trayMenu.closeMenu()
            mouse.accepted = true
        }
    }

    Connections {
        target: (typeof App !== "undefined" && App && App.tray) ? App.tray : null
        function onTrayContextMenuRequested(x, y) {
            trayMenu.toggleAt(x, y)
        }
        function onTrayPrimaryClicked() {
            if (trayMenu.visible)
                trayMenu.closeMenu()
            else if (typeof App !== "undefined" && App && App.tray)
                App.tray.showMainWindow()
        }
    }

    Connections {
        target: root.windowObject
        function onWindowEvent(type, payload) {
            if (typeof App !== "undefined" && App && App.window)
                App.window.handleWindowEvent(root.windowObject.windowKey, type, payload)
        }
    }

    Component.onCompleted: {
        if (typeof App !== "undefined" && App && App.tray)
            App.tray.registerWindow(root.windowObject)
    }
}
