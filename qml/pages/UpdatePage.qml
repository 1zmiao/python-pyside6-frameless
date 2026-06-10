import QtQuick
import "../core" as Core
import "../controls"

Item {
    DragScrollArea {
        anchors.fill: parent

        Rectangle {
            width: parent.width
            height: Math.max(Core.Theme.dp(220), updateContent.implicitHeight + Core.Theme.dp(36))
            radius: Core.Theme.radius.card
            color: Core.Theme.color.card
            border.color: Core.Theme.color.cardOutline
            Behavior on border.color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
            Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }

            BackgroundRipple { radius: parent.radius }
            CardAccentGlow { radius: parent.radius }

            Column {
                id: updateContent
                z: 1
                anchors.fill: parent
                anchors.margins: 18
                spacing: 10
                Text { text: "更新"; color: Core.Theme.color.text; font.pixelSize: Core.Theme.sp(24); font.family: Core.Theme.headingFontFamily; font.weight: Core.Theme.headingFontWeight; font.letterSpacing: Core.Theme.headingLetterSpacing }
                Text { width: parent.width; text: "这里可以放置更新界面。网络请求和更新逻辑建议放在 Python 中，并通过安全信号暴露给 QML。"; color: Core.Theme.color.mutedText; font.pixelSize: Core.Theme.fontSize.body; wrapMode: Text.WordWrap; lineHeight: Core.Theme.bodyLineHeight }
                AppButton { text: "检查更新占位按钮" }
            }
        }
    }
}
