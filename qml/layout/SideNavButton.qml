import QtQuick
import "../core" as Core
import "../controls"

Item {
    id: root

    property string page: ""
    property string text: ""
    property string iconName: ""
    property bool selected: false
    property bool compact: false

    signal clicked()

    width: parent ? parent.width : 180
    height: 36

    Rectangle {
        anchors.fill: parent
        radius: Core.Theme.radius.button
        color: root.selected ? Core.Theme.color.navActive : (mouse.containsMouse ? Core.Theme.color.controlHover : "transparent")
        border.color: root.selected ? Core.Theme.primaryOutline : "transparent"
        border.width: root.selected ? 1 : 0
    }

    IconImage {
        x: root.compact ? Math.round((parent.width - width) / 2) : Core.Theme.dp(11)
        anchors.verticalCenter: parent.verticalCenter
        width: Core.Theme.dp(15)
        height: width
        iconName: root.iconName
        iconColor: root.selected ? Core.Theme.color.navSelectedIcon : Core.Theme.color.icon
        strokeWidth: 1.05
    }

    Text {
        anchors.left: parent.left
        anchors.leftMargin: Core.Theme.dp(34)
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        text: root.text
        visible: !root.compact
        color: root.selected ? Core.Theme.color.navSelectedText : Core.Theme.color.text
        font.pixelSize: Core.Theme.fontSize.control
        font.family: Core.Theme.appFontFamily
        font.bold: root.selected
        elide: Text.ElideRight
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        onClicked: root.clicked()
    }
}
