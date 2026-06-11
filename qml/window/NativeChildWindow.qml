import QtQuick
import QtQuick.Window
import "."

AppWindow {
    id: child
    bridge: App
    autoRestoreWindowState: false
    autoShow: false
    destroyOnChildClose: true
    showNavToggle: false
    showColorButton: false
    showThemeButton: false
    showPinButton: childTopmostEnabled
    title: pageTitle
    width: 760
    height: 520
    minimumWidth: 520
    minimumHeight: 360

    property var parentWindow: null
    property string pageSource: ""
    property string pageTitle: "子窗口"
    property bool childTopmostEnabled: false
    property bool contentReleased: false

    modality: Qt.NonModal

    Loader {
        id: pageLoader
        anchors.fill: parent
        asynchronous: true
        active: !child.contentReleased
        source: child.contentReleased ? "" : child.pageSource
    }

    function prepareContent(sourceUrl) {
        alwaysOnTop = false
        _childCloseScheduled = false
        pageSource = sourceUrl
        contentReleased = false
    }

    function releaseContent() {
        contentReleased = true
        pageSource = ""
        pageLoader.source = ""
        pageLoader.active = false
    }

    function applyParentWindow() {
        if (parentWindow !== null && parentWindow !== undefined) {
            x = parentWindow.x + 80
            y = parentWindow.y + 80
        }
    }

    function refreshChildTopmostEnabled() {
        const enabled = (typeof App !== "undefined" && App && App.settings)
                        ? App.settings.valueOr("performance/childWindowTopmostEnabled", false)
                        : false
        if (childTopmostEnabled === enabled)
            return
        if (!enabled && childTopmostEnabled && titleBar && titleBar.pinButtonItem)
            unregisterNativeClickableItem(titleBar.pinButtonItem)
        childTopmostEnabled = enabled
        if (!enabled && alwaysOnTop) {
            alwaysOnTop = false
            if (bridge && bridge.window)
                bridge.window.setAlwaysOnTop(child, false)
        }
    }

    onParentWindowChanged: applyParentWindow()
    Component.onCompleted: {
        refreshChildTopmostEnabled()
        applyParentWindow()
    }

    Connections {
        target: (typeof App !== "undefined" && App && App.settings) ? App.settings : null
        function onChanged(key, value) {
            if (key === "performance/childWindowTopmostEnabled")
                child.refreshChildTopmostEnabled()
        }
    }
}
