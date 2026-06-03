import QtQuick
import "../core" as Core

Item {
    id: root

    property int radius: Core.Theme.radius.card
    property string liveHex: String(Core.Theme.primary).replace("#", "")
    property string modeKey: Core.Theme.mode
    property int pixelWidth: Math.max(1, Math.round(width))
    property int pixelHeight: Math.max(1, Math.round(height))
    property int pixelRadius: Math.max(0, Math.round(radius))

    property bool lowMemoryVisuals: Core.Theme.lowMemoryMode
                                    && root.Window.window
                                    && String(root.Window.window.windowKey || "") !== "main"

    anchors.fill: parent
    visible: width > 0 && height > 0 && !root.lowMemoryVisuals

    function imageName() {
        return "image://cardaccent/card/" + root.modeKey + "/" + root.liveHex + "/" + root.pixelRadius + "/" + root.pixelWidth + "x" + root.pixelHeight
    }

    Loader {
        anchors.fill: parent
        active: !root.lowMemoryVisuals && root.visible
        sourceComponent: Image {
            anchors.fill: parent
            sourceSize.width: root.pixelWidth
            sourceSize.height: root.pixelHeight
            source: root.imageName()
            fillMode: Image.Stretch
            smooth: true
            asynchronous: false
            mipmap: false
            cache: false
            opacity: 1.0
        }
    }
}
