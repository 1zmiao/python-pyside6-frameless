import QtQuick
import "../core" as Core
import "../controls"

Item {
    id: root

    property bool appReady: typeof App !== "undefined" && App !== null
    property var memorySample: ({ "rss": 0, "private": 0 })

    function refreshMemorySample() {
        if (root.appReady && App.memorySample)
            root.memorySample = App.memorySample()
    }

    Component.onCompleted: root.refreshMemorySample()

    Timer {
        interval: 1000
        repeat: true
        running: true
        triggeredOnStart: false
        onTriggered: root.refreshMemorySample()
    }

    DragScrollArea {
        anchors.fill: parent
        spacing: Core.Theme.dp(16)

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
                anchors.margins: Core.Theme.dp(18)
                spacing: Core.Theme.dp(10)

                Text {
                    text: "\u66f4\u65b0"
                    color: Core.Theme.color.text
                    font.pixelSize: Core.Theme.sp(24)
                    font.family: Core.Theme.headingFontFamily
                    font.weight: Core.Theme.headingFontWeight
                    font.letterSpacing: Core.Theme.headingLetterSpacing
                }

                Text {
                    width: parent.width
                    text: "\u8fd9\u91cc\u53ef\u4ee5\u653e\u7f6e\u66f4\u65b0\u754c\u9762\u3002\u7f51\u7edc\u8bf7\u6c42\u548c\u66f4\u65b0\u903b\u8f91\u5efa\u8bae\u653e\u5728 Python \u4e2d\uff0c\u5e76\u901a\u8fc7\u5b89\u5168\u4fe1\u53f7\u66b4\u9732\u7ed9 QML\u3002"
                    color: Core.Theme.color.mutedText
                    font.pixelSize: Core.Theme.fontSize.body
                    wrapMode: Text.WordWrap
                    lineHeight: Core.Theme.bodyLineHeight
                }

                AppButton { text: "\u68c0\u67e5\u66f4\u65b0" }
            }
        }

        Rectangle {
            width: parent.width
            height: Math.max(Core.Theme.dp(156), memoryContent.implicitHeight + Core.Theme.dp(36))
            radius: Core.Theme.radius.card
            color: Core.Theme.color.card
            border.color: Core.Theme.color.cardOutline
            Behavior on border.color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
            Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }

            BackgroundRipple { radius: parent.radius }
            CardAccentGlow { radius: parent.radius }

            Column {
                id: memoryContent
                z: 1
                anchors.fill: parent
                anchors.margins: Core.Theme.dp(18)
                spacing: Core.Theme.dp(8)

                Text {
                    text: "\u8fd0\u884c\u72b6\u6001"
                    color: Core.Theme.color.text
                    font.pixelSize: Core.Theme.fontSize.subtitle
                    font.family: Core.Theme.headingFontFamily
                    font.weight: Core.Theme.headingFontWeight
                    font.letterSpacing: Core.Theme.headingLetterSpacing
                }

                Text {
                    width: parent.width
                    text: "\u5f53\u524d\u79c1\u6709\u9a7b\u7559\u5185\u5b58\uff1a" + Number(root.memorySample["ws_private"] || 0).toFixed(1) + " MB"
                    color: Core.Theme.color.text
                    font.pixelSize: Core.Theme.fontSize.body
                    font.family: Core.Theme.appFontFamily
                }

                Text {
                    width: parent.width
                    text: "\u8fd9\u4e2a\u53e3\u5f84\u5bf9\u5e94 Working Set - Private\uff0c\u66f4\u63a5\u8fd1\u7528\u6237\u5728\u4efb\u52a1\u7ba1\u7406\u5668\u91cc\u5173\u5fc3\u7684\u5f53\u524d\u5b9e\u9645\u79c1\u6709\u5185\u5b58\u3002"
                    color: Core.Theme.color.mutedText
                    font.pixelSize: Core.Theme.fontSize.caption
                    font.family: Core.Theme.appFontFamily
                    wrapMode: Text.WordWrap
                    lineHeight: Core.Theme.bodyLineHeight
                }

            }
        }
    }
}
