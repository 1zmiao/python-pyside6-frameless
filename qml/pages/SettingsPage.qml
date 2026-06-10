import QtQuick
import QtQuick.Controls
import "../core" as Core
import "../controls"

Item {
    id: root

    property bool appReady: typeof App !== "undefined" && App !== null
    function settingValue(key, fallback) { return appReady && App.settings ? App.settings.valueOr(key, fallback) : fallback }
    function settingsPath() { return appReady && App.settings ? App.settings.path() : "" }
    function trayIconPath() { return appReady && App.tray ? App.tray.iconPath : "resources/app_icon.ico" }
    function trayDefaultIconPath() { return appReady && App.tray ? App.tray.defaultIconPath() : "resources/app_icon.ico" }
    function performanceProfile() { return appReady && App.performance ? App.performance.resourceProfile : "auto" }
    function effectiveProfile() { return appReady && App.performance ? App.performance.effectiveProfile : "normal" }
    function profileIndex(profile) {
        if (profile === "normal") return 1
        if (profile === "low-memory") return 2
        return 0
    }
    function profileFromIndex(index) {
        if (index === 1) return "normal"
        if (index === 2) return "low-memory"
        return "auto"
    }
    function toastHost() {
        var w = root.Window.window
        if (w && w.showToast)
            return w
        if (typeof NativeHost !== "undefined" && NativeHost && NativeHost.showToast)
            return NativeHost
        return null
    }
    function showToast(message) {
        const host = root.toastHost()
        if (host && host.showToast)
            host.showToast(message)
    }

    DragScrollArea {
        anchors.fill: parent
        spacing: Core.Theme.dp(16)

        Rectangle {
            width: parent.width
            height: settingsColumn.implicitHeight + Core.Theme.dp(36)
            radius: Core.Theme.radius.card
            color: Core.Theme.color.card
            border.color: Core.Theme.color.cardOutline
            Behavior on border.color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
            Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
            antialiasing: true

            BackgroundRipple { radius: parent.radius }
            CardAccentGlow { radius: parent.radius }

            Column {
                id: settingsColumn
                z: 1
                anchors.fill: parent
                anchors.margins: Core.Theme.dp(18)
                spacing: Core.Theme.dp(12)

                Text { text: "设置"; color: Core.Theme.color.text; font.pixelSize: Core.Theme.fontSize.title; font.family: Core.Theme.headingFontFamily; font.weight: Core.Theme.headingFontWeight; font.letterSpacing: Core.Theme.headingLetterSpacing }
                Text { width: parent.width; text: "这些设置会保存在软件根目录下的本地 JSON 配置文件中。"; color: Core.Theme.color.mutedText; font.pixelSize: Core.Theme.fontSize.body; wrapMode: Text.WordWrap; lineHeight: Core.Theme.bodyLineHeight }
                Text { width: parent.width; text: root.settingsPath(); color: Core.Theme.color.mutedText; font.pixelSize: Core.Theme.fontSize.caption; elide: Text.ElideRight }

                AppCheckBox { text: "启用功能 A"; storageKey: "settings/featureA"; checked: true; autoLoad: true }
                AppCheckBox { text: "启用功能 B"; storageKey: "settings/featureB"; autoLoad: true }
                AppCheckBox {
                    text: "关闭窗口到托盘图标"
                    checked: root.appReady && App.tray ? App.tray.closeToTray : root.settingValue("window/closeToTray", root.settingValue("window/minimizeToTray", false))
                    onToggled: {
                        if (root.appReady && App.tray)
                            App.tray.setCloseToTray(checked)
                        else if (root.appReady && App.settings)
                            App.settings.setValue("window/closeToTray", checked)
                    }
                }
                AppCheckBox {
                    text: "显示标题栏调色按钮"
                    checked: Core.Theme.showColorButton
                    onClicked: {
                        if (root.appReady && App.theme) App.theme.setShowColorButton(checked)
                        else if (root.appReady && App.settings) App.settings.setValue("ui/showColorButton", checked)
                    }
                }

                Rectangle { width: parent.width; height: 1; color: Core.Theme.color.hairline; opacity: 0.75 }

                Column {
                    width: parent.width
                    spacing: Core.Theme.dp(6)
                    Flow {
                        width: parent.width
                        spacing: Core.Theme.dp(8)
                        Text { text: "界面字体大小（Ctrl+滚轮）"; color: Core.Theme.color.text; font.pixelSize: Core.Theme.fontSize.body; width: Core.Theme.dp(168); height: Core.Theme.metrics.controlHeight; verticalAlignment: Text.AlignVCenter }
                        Text { text: Math.round(13 * Core.Theme.fontScale) + " px / " + Math.round(Core.Theme.fontScale * 100) + "%"; color: Core.Theme.color.mutedText; font.pixelSize: Core.Theme.fontSize.control; width: Core.Theme.dp(94); height: Core.Theme.metrics.controlHeight; verticalAlignment: Text.AlignVCenter }
                        AppButton { text: "重置"; variant: "soft"; minWidth: Core.Theme.dp(56); horizontalPadding: Core.Theme.dp(12); onClicked: if (root.appReady && App.theme) App.theme.resetFontScale() }
                    }
                    Slider {
                        id: fontSlider
                        width: parent.width
                        from: 85
                        to: 130
                        stepSize: 5
                        snapMode: Slider.SnapAlways
                        value: Math.round(Core.Theme.fontScale * 100 / 5) * 5
                        live: true
                        onMoved: if (root.appReady && App.theme) App.theme.setFontScale(value / 100.0)
                        background: Item {
                            x: fontSlider.leftPadding
                            y: fontSlider.topPadding + fontSlider.availableHeight / 2 - height / 2
                            implicitWidth: Core.Theme.dp(200)
                            implicitHeight: Core.Theme.dp(18)
                            width: fontSlider.availableWidth
                            height: implicitHeight
                            Rectangle {
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width
                                height: Core.Theme.dp(4)
                                radius: 2
                                color: Core.Theme.primarySoft
                                Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                            }
                            Rectangle {
                                anchors.verticalCenter: parent.verticalCenter
                                width: fontSlider.visualPosition * parent.width
                                height: Core.Theme.dp(4)
                                radius: 2
                                color: Core.Theme.primary
                                Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                            }
                            Repeater {
                                model: 10
                                delegate: Rectangle {
                                    width: Core.Theme.dp(2)
                                    height: Core.Theme.dp(index % 2 === 0 ? 10 : 7)
                                    radius: 1
                                    color: Core.Theme.mode === "dark" ? "#A8A3C7" : "#667085"
                                    opacity: 0.75
                                    x: index * (parent.width - width) / 9
                                    anchors.verticalCenter: parent.verticalCenter
                                    Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                                }
                            }
                        }
                        handle: Rectangle {
                            x: fontSlider.leftPadding + fontSlider.visualPosition * (fontSlider.availableWidth - width)
                            y: fontSlider.topPadding + fontSlider.availableHeight / 2 - height / 2
                            width: Core.Theme.dp(20)
                            height: Core.Theme.dp(20)
                            radius: width / 2
                            color: Core.Theme.primary
                            border.color: Core.Theme.color.card
                            border.width: 2
                            Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                            Behavior on border.color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                        }
                    }
                    Connections { target: root.appReady && App.theme ? App.theme : null; function onFontScaleChanged(scale) { fontSlider.value = Math.round(scale * 100 / fontSlider.stepSize) * fontSlider.stepSize } }
                    Row {
                        width: parent.width
                        spacing: 0
                        Repeater { model: ["85", "90", "95", "100", "105", "110", "115", "120", "125", "130"]; delegate: Text { width: parent.width / 10; text: modelData; color: Core.Theme.color.mutedText; font.pixelSize: Core.Theme.fontSize.caption; horizontalAlignment: Text.AlignHCenter } }
                    }
                }

                Column {
                    width: parent.width
                    spacing: Core.Theme.dp(6)
                    Text { width: parent.width; text: "托盘图标文件：" + root.trayIconPath(); color: Core.Theme.color.mutedText; font.pixelSize: Core.Theme.fontSize.caption; elide: Text.ElideRight }
                    Text { width: parent.width; text: "默认图标位置：" + root.trayDefaultIconPath(); color: Core.Theme.color.mutedText; font.pixelSize: Core.Theme.fontSize.caption; elide: Text.ElideRight }
                    Text { width: parent.width; text: "可以直接替换默认 PNG，也可以在下面输入 PNG/ICO 的绝对路径并保存。"; color: Core.Theme.color.mutedText; font.pixelSize: Core.Theme.fontSize.caption; wrapMode: Text.WordWrap; lineHeight: Core.Theme.bodyLineHeight }
                }

                AppTextField { id: trayIconPathInput; width: parent.width; placeholderText: "自定义托盘图标路径，可留空"; storageKey: "tray/iconPath"; autoLoad: true; onSaved: if (root.appReady && App.tray) App.tray.setIconPath(text) }
                AppTextField { id: projectPathInput; width: parent.width; placeholderText: "默认项目路径"; storageKey: "paths/defaultProject"; autoLoad: true }

                Flow {
                    width: parent.width
                    spacing: Core.Theme.dp(8)
                    AppButton {
                        variant: "primary"
                        text: "保存设置"
                        onClicked: {
                            if (!root.appReady || !App.settings) return
                            App.settings.setValue("paths/defaultProject", projectPathInput.text)
                            App.settings.setValue("tray/iconPath", trayIconPathInput.text)
                            if (App.tray)
                                App.tray.setIconPath(trayIconPathInput.text)
                            root.showToast("设置已保存")
                        }
                    }
                    AppButton {
                        variant: "soft"
                        text: "切换日夜主题"
                        onClicked: {
                            if (!root.appReady || !App.theme) return
                            const next = Core.Theme.mode === "dark" ? "light" : "dark"
                            const host = root.Window.window
                            if (host && host.changeThemeWithRipple)
                                host.changeThemeWithRipple(next, host.width / 2, host.height / 2)
                            else if (typeof NativeHost !== "undefined" && NativeHost && NativeHost.changeThemeWithRipple)
                                NativeHost.changeThemeWithRipple(next, root.width / 2, root.height / 2)
                            else
                                App.theme.setMode(next)
                        }
                    }
                }
            }
        }

        Rectangle {
            width: parent.width
            height: memoryColumn.implicitHeight + Core.Theme.dp(36)
            radius: Core.Theme.radius.card
            color: Core.Theme.color.card
            border.color: Core.Theme.color.cardOutline
            Behavior on border.color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
            Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
            antialiasing: true

            BackgroundRipple { radius: parent.radius }
            CardAccentGlow { radius: parent.radius }

            Column {
                id: memoryColumn
                z: 1
                anchors.fill: parent
                anchors.margins: Core.Theme.dp(18)
                spacing: Core.Theme.dp(12)

                Text {
                    text: "内存优化管理"
                    color: Core.Theme.color.text
                    font.pixelSize: Core.Theme.fontSize.subtitle
                    font.family: Core.Theme.headingFontFamily
                    font.weight: Core.Theme.headingFontWeight
                    font.letterSpacing: Core.Theme.headingLetterSpacing
                }

                Text {
                    width: parent.width
                    text: "进一步的内存优化需开启开发者选项强制设置。默认密码：code"
                    color: Core.Theme.color.mutedText
                    font.pixelSize: Core.Theme.fontSize.caption
                    font.family: Core.Theme.appFontFamily
                    wrapMode: Text.WordWrap
                    lineHeight: Core.Theme.bodyLineHeight
                }

                AppCheckBox {
                    width: parent.width
                    wrapText: true
                    text: "独立子窗口启用置顶按钮（每个独立子窗口会额外增加约 3MB 内存占用量）"
                    storageKey: "performance/childWindowTopmostEnabled"
                    checked: false
                    autoLoad: true
                }
            }
        }

        Rectangle {
            width: parent.width
            height: developerColumn.implicitHeight + Core.Theme.dp(36)
            radius: Core.Theme.radius.card
            color: Core.Theme.color.card
            border.color: Core.Theme.color.cardOutline
            Behavior on border.color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
            Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
            antialiasing: true

            BackgroundRipple { radius: parent.radius }
            CardAccentGlow { radius: parent.radius }

            Column {
                id: developerColumn
                z: 1
                anchors.fill: parent
                anchors.margins: Core.Theme.dp(18)
                spacing: Core.Theme.dp(12)

                Text { text: "开发者选项"; color: Core.Theme.color.text; font.pixelSize: Core.Theme.fontSize.subtitle; font.family: Core.Theme.headingFontFamily; font.weight: Core.Theme.headingFontWeight; font.letterSpacing: Core.Theme.headingLetterSpacing }

                Text {
                    width: parent.width
                    visible: root.appReady && App.performance && App.performance.developerKeyPresent
                    text: "已检测到本机 developer.key，开发者选项已自动展开。路径：" + (root.appReady && App.performance ? App.performance.developerKeyPath : "")
                    color: Core.Theme.color.mutedText
                    font.pixelSize: Core.Theme.fontSize.caption
                    font.family: Core.Theme.appFontFamily
                    wrapMode: Text.WrapAnywhere
                }
                Text {
                    width: parent.width
                    visible: root.appReady && App.performance && App.performance.developerUnlocked && !App.performance.developerKeyPresent
                    text: "已通过维护口令开启开发者选项。"
                    color: Core.Theme.color.mutedText
                    font.pixelSize: Core.Theme.fontSize.caption
                    font.family: Core.Theme.appFontFamily
                    wrapMode: Text.WordWrap
                    lineHeight: Core.Theme.bodyLineHeight
                }

                Flow {
                    width: parent.width
                    spacing: Core.Theme.dp(8)
                    visible: !(root.appReady && App.performance && App.performance.developerUnlocked)
                    AppTextField { id: developerPasswordInput; width: Math.min(Core.Theme.dp(260), Math.max(Core.Theme.dp(150), parent.width - unlockButton.width - Core.Theme.dp(8))); placeholderText: "维护口令"; encrypted: true; revealed: false; autoSave: false }
                    AppButton {
                        id: unlockButton
                        variant: "soft"
                        height: developerPasswordInput.height
                        text: "开启"
                        minButtonWidth: Core.Theme.dp(82)
                        onClicked: {
                            if (!root.appReady || !App.performance)
                                return
                            if (App.performance.unlockDeveloperMode(developerPasswordInput.text))
                                root.showToast("开发者选项已开启")
                            else
                                root.showToast("口令不正确")
                        }
                    }
                }

                Column {
                    width: parent.width
                    spacing: Core.Theme.dp(8)
                    visible: root.appReady && App.performance && App.performance.developerUnlocked

                    Flow {
                        width: parent.width
                        spacing: Core.Theme.dp(10)
                        Text { text: "资源档位"; color: Core.Theme.color.text; font.pixelSize: Core.Theme.fontSize.body; width: Core.Theme.dp(86); height: Core.Theme.metrics.controlHeight; verticalAlignment: Text.AlignVCenter }
                        ComboBox {
                            id: profileCombo
                            property int rowHeight: Core.Theme.dp(34)
                            width: Math.min(Core.Theme.dp(230), Math.max(Core.Theme.dp(150), parent.width - Core.Theme.dp(96)))
                            height: Core.Theme.metrics.controlHeight
                            model: ["自动", "普通模式", "低内存模拟"]
                            currentIndex: root.profileIndex(root.performanceProfile())
                            onActivated: function(index) {
                                if (root.appReady && App.performance)
                                    App.performance.setResourceProfile(root.profileFromIndex(index))
                            }
                            contentItem: Text {
                                leftPadding: Core.Theme.dp(12)
                                rightPadding: Core.Theme.dp(32)
                                text: profileCombo.displayText
                                color: Core.Theme.color.text
                                font.pixelSize: Core.Theme.fontSize.control
                                font.family: Core.Theme.appFontFamily
                                verticalAlignment: Text.AlignVCenter
                                elide: Text.ElideRight
                                Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                            }
                            indicator: Text {
                                text: "▼"
                                color: Core.Theme.color.mutedText
                                font.pixelSize: Core.Theme.fontSize.tiny
                                font.family: Core.Theme.appFontFamily
                                anchors.right: parent.right
                                anchors.rightMargin: Core.Theme.dp(10)
                                anchors.verticalCenter: parent.verticalCenter
                                Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                            }
                            background: Rectangle {
                                radius: Core.Theme.radius.button
                                color: profileCombo.pressed ? Core.Theme.color.controlPressed : (profileCombo.hovered ? Core.Theme.color.controlHover : Core.Theme.color.field)
                                border.color: profileCombo.activeFocus ? Core.Theme.color.fieldFocusBorder : Core.Theme.color.outline
                                border.width: 1
                                Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                                Behavior on border.color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                            }
                            delegate: ItemDelegate {
                                width: profileCombo.width
                                height: profileCombo.rowHeight
                                highlighted: profileCombo.highlightedIndex === index
                                contentItem: Text {
                                    text: modelData
                                    color: highlighted ? Core.Theme.color.navSelectedText : Core.Theme.color.text
                                    font.pixelSize: Core.Theme.fontSize.control
                                    font.family: Core.Theme.appFontFamily
                                    verticalAlignment: Text.AlignVCenter
                                    leftPadding: Core.Theme.dp(10)
                                    elide: Text.ElideRight
                                    Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                                }
                                background: Rectangle {
                                    radius: Core.Theme.radius.button
                                    color: highlighted ? Core.Theme.color.navActive : (hovered ? Core.Theme.color.controlHover : Core.Theme.alpha(Core.Theme.color.controlHover, 0))
                                    Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                                }
                            }
                            popup: Popup {
                                y: profileCombo.height + Core.Theme.dp(4)
                                width: profileCombo.width
                                padding: Core.Theme.dp(4)
                                implicitHeight: contentItem.implicitHeight + padding * 2
                                background: Rectangle {
                                    radius: Core.Theme.radius.popup
                                    color: Core.Theme.color.card
                                    border.color: Core.Theme.color.outlineAccent
                                    border.width: 1
                                    Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                                    Behavior on border.color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
                                }
                                contentItem: ListView {
                                    clip: true
                                    implicitHeight: Math.min(contentHeight, profileCombo.rowHeight * 3)
                                    model: profileCombo.popup.visible ? profileCombo.delegateModel : null
                                    currentIndex: profileCombo.highlightedIndex
                                }
                            }
                        }
                    }

                    Text {
                        width: parent.width
                        text: "当前生效：" + (root.effectiveProfile() === "low-memory" ? "低内存" : "普通") + "。自动模式只在 4GB 及以下内存设备上进入低内存策略。"
                        color: Core.Theme.color.mutedText
                        font.pixelSize: Core.Theme.fontSize.caption
                        font.family: Core.Theme.appFontFamily
                        wrapMode: Text.WordWrap
                        lineHeight: Core.Theme.bodyLineHeight
                    }
                    Text {
                        width: parent.width
                        text: "切换后需重开子窗口才会完整生效。"
                        color: Core.Theme.color.mutedText
                        font.pixelSize: Core.Theme.fontSize.caption
                        font.family: Core.Theme.appFontFamily
                        wrapMode: Text.WordWrap
                        lineHeight: Core.Theme.bodyLineHeight
                    }

                    Connections {
                        target: root.appReady && App.performance ? App.performance : null
                        function onResourceProfileChanged(profile) { profileCombo.currentIndex = root.profileIndex(profile) }
                    }
                }
            }
        }
    }
}
