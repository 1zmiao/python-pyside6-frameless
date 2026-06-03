import QtQuick
import "../core" as Core
import "../window"

Item {
    id: root
    anchors.fill: parent
    enabled: false
    visible: rippleLoader.item ? rippleLoader.item.running : false

    property int radius: Core.Theme.radius.card
    property real startX: width * 0.82
    property real startY: height * 0.18
    property int delayMs: Math.max(0, Math.round((root.x * 0.37 + root.y * 0.23) % 220))
    property real opacityScale: 0.62
    property bool lowMemoryVisuals: root.Window.window
                                    && String(root.Window.window.windowKey || "") !== "main"

    Loader {
        id: rippleLoader
        anchors.fill: parent
        active: !root.lowMemoryVisuals
        sourceComponent: ThemeTransitionLayer {
            radius: root.radius
            startDelay: root.delayMs
            opacityScale: root.opacityScale
        }
    }

    Connections {
        target: (typeof App !== "undefined" && App && App.theme) ? App.theme : null
        function onModeChanged(mode) {
            if (!rippleLoader.item)
                return
            const px = root.startX
            const py = root.startY
            rippleLoader.item.play(px, py, mode)
        }
    }
}
