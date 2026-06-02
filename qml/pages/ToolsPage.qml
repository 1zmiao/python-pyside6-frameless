import QtQuick
import "../core" as Core
import "../controls"

Item {
    DragScrollArea {
        anchors.fill: parent

        Rectangle {
            width: parent.width
            height: Math.max(Core.Theme.dp(220), toolContent.implicitHeight + Core.Theme.dp(36))
            radius: Core.Theme.radius.card
            color: Core.Theme.color.card
            border.color: Core.Theme.color.outlineAccent

            BackgroundRipple { radius: parent.radius }
            CardAccentGlow { radius: parent.radius }

            Column {
                id: toolContent
                z: 1
                anchors.fill: parent
                anchors.margins: 18
                spacing: 10
                Text { text: "工具"; color: Core.Theme.color.text; font.pixelSize: Core.Theme.sp(24); font.family: Core.Theme.headingFontFamily; font.weight: Core.Theme.headingFontWeight; font.letterSpacing: Core.Theme.headingLetterSpacing }
                Text { width: parent.width; text: "这里可以放置软件专属工具。重型控件建议懒加载，或由 C++/Python 模型暴露给 QML。"; color: Core.Theme.color.mutedText; font.pixelSize: Core.Theme.fontSize.body; wrapMode: Text.WordWrap }
                Row {
                    spacing: 8
                    AppButton { text: "工具操作"; variant: "primary" }
                    AppButton { text: "打开关于子窗口"; onClicked: App.dialogs.openChild(null, "about", ({})) }
                }
            }
        }
    }
}
