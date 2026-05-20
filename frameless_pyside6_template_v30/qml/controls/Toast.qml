import QtQuick
import "../core" as Core

Item {
    id: root
    width: label.implicitWidth + Core.Theme.dp(58)
    height: Core.Theme.dp(42)
    opacity: 0
    visible: opacity > 0

    property alias text: label.text
    signal expired()

    Rectangle {
        anchors.fill: parent
        radius: height / 2
        border.color: Core.Theme.mode === "dark" ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(0, 0, 0, 0.14)
        border.width: 1
        color: Core.Theme.mode === "dark" ? "#2A2D35" : "#2F2B33"
    }

    Text {
        id: label
        anchors.centerIn: parent
        color: "white"
        font.pixelSize: Core.Theme.sp(14)
        font.bold: false
    }

    Timer {
        id: timer
        interval: 2100
        onTriggered: fadeOut.start()
    }

    NumberAnimation on opacity {
        id: fadeOut
        from: 1
        to: 0
        duration: 180
        onStopped: {
            if (root.opacity <= 0.01)
                root.expired()
        }
    }

    function show(message) {
        label.text = message
        fadeOut.stop()
        opacity = 1
        timer.restart()
    }
}
