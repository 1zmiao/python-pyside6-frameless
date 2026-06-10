import QtQuick
import "../core" as Core
import "../controls"

Item {
    DragScrollArea {
        anchors.fill: parent

        Rectangle {
            width: parent.width
            height: Math.max(Core.Theme.dp(240), toolContent.implicitHeight + Core.Theme.dp(36))
            radius: Core.Theme.radius.card
            color: Core.Theme.color.card
            border.color: Core.Theme.color.cardOutline
            Behavior on border.color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
            Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
            antialiasing: true

            BackgroundRipple { radius: parent.radius }
            CardAccentGlow { radius: parent.radius }

            Column {
                id: toolContent
                z: 1
                anchors.fill: parent
                anchors.margins: Core.Theme.dp(18)
                spacing: Core.Theme.dp(10)

                Text {
                    text: "工具"
                    color: Core.Theme.color.text
                    font.pixelSize: Core.Theme.fontSize.title
                    font.family: Core.Theme.headingFontFamily
                    font.weight: Core.Theme.headingFontWeight
                    font.letterSpacing: Core.Theme.headingLetterSpacing
                }

                Text {
                    width: parent.width
                    text: "这里可以放项目专属工具。重型控件建议懒加载，或把 C++/Python 模型暴露给 QML。"
                    color: Core.Theme.color.mutedText
                    font.pixelSize: Core.Theme.fontSize.body
                    wrapMode: Text.WordWrap
                    lineHeight: Core.Theme.bodyLineHeight
                }

                Flow {
                    width: parent.width
                    spacing: Core.Theme.dp(8)
                    AppButton { text: "工具操作"; variant: "primary" }
                    AppButton { text: "打开页内子窗口"; variant: "soft"; onClicked: Core.InlineWindowBus.openInline("inline-demo", ({})) }
                    AppButton { text: "打开关于子窗口"; onClicked: Core.InlineWindowBus.openNative("about", ({})) }
                }
            }
        }
    }
}
