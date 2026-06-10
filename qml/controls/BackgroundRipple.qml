import QtQuick
import "../core" as Core
import "../window"

Item {
    id: root
    anchors.fill: parent
    enabled: false
    visible: rippleLoader.item ? rippleLoader.item.running : false

    property int radius: Core.Theme.radius.card
    property real startX: width * 0.92
    property real startY: height * 0.08
    property int delayMs: Math.max(0, Math.round((root.x * 0.19 + root.y * 0.13) % 92))
    property real opacityScale: 0.46
    property string colorRole: "card"
    property string pendingMode: ""
    property real pendingX: 0
    property real pendingY: 0
    property bool lowMemoryVisuals: Core.Theme.lowMemoryMode
                                    && root.Window.window
                                    && root.Window.window.windowKey !== undefined
                                    && String(root.Window.window.windowKey) !== "main"

    function play(px, py, mode) {
        if (root.lowMemoryVisuals)
            return
        pendingX = px
        pendingY = py
        pendingMode = mode
        if (rippleLoader.item) {
            rippleLoader.item.play(pendingX, pendingY, pendingMode)
        } else {
            rippleLoader.active = true
        }
    }

    Loader {
        id: rippleLoader
        anchors.fill: parent
        active: false
        sourceComponent: ThemeTransitionLayer {
            radius: root.radius
            colorRole: root.colorRole
            startDelay: root.delayMs
            opacityScale: root.opacityScale
            onFinished: {
                root.pendingMode = ""
                rippleLoader.active = false
                if (typeof App !== "undefined" && App && App.trimMemory)
                    Qt.callLater(App.trimMemory)
            }
        }
        onLoaded: {
            if (item && root.pendingMode.length > 0)
                item.play(root.pendingX, root.pendingY, root.pendingMode)
        }
    }

    Connections {
        target: (typeof App !== "undefined" && App && App.theme) ? App.theme : null
        function onModeChanged(mode) {
            root.play(root.startX, root.startY, mode)
        }
    }
}
