import QtQuick
import QtQuick.Controls
import QtQuick.Window
import "core" as Core
import "window"
import "layout"
import "controls"

Item {
    id: root
    width: 1080
    height: 700

    readonly property real devicePixelRatio: Math.max(1.0, (root.Window.window && root.Window.window.screen) ? root.Window.window.screen.devicePixelRatio : Screen.devicePixelRatio)
    readonly property real physicalPixel: 1.0 / devicePixelRatio
    readonly property real stableHairline: Math.max(1.0, physicalPixel)
    function snapToPhysicalPixel(value) {
        return Math.round(value / physicalPixel) * physicalPixel
    }

    property string windowKey: "main"
    property bool nativeMaximized: false
    property bool nativeSnapped: false
    property bool nativeCustomShadow: (typeof NativeHost !== "undefined" && NativeHost) ? NativeHost.customShadowEnabled : false
    property int cornerRadius: nativeMaximized ? 0 : Core.Theme.radius.window
    property alias titleBar: titleBar
    property bool _localThemeAnimation: false
    property bool snapShadowSuppressed: false
    property bool nativeDragRestoreVisual: false
    property int normalShadowVisualInset: Core.Theme.dp(32)
    property bool inlineShadowVisible: nativeCustomShadow
                                       && !snapShadowSuppressed
                                       && !nativeMaximized
                                       && !nativeSnapped
                                       && !nativeDragRestoreVisual
    property bool normalVisualMarginsActive: inlineShadowVisible || (nativeCustomShadow && nativeDragRestoreVisual)
    property int shadowVisualInset: normalVisualMarginsActive ? normalShadowVisualInset : 0

    function showToast(message) {
        toastModel.append({ "message": message, "createdAt": Date.now() })
        while (toastModel.count > 5)
            toastModel.remove(0)
    }

    function changeThemeWithRipple(nextMode, px, py) {
        if (nextMode !== "dark" && nextMode !== "light")
            return
        if (nextMode === Core.Theme.mode)
            return
        const cx = px === undefined ? frameRoot.width / 2 : px
        const cy = py === undefined ? frameRoot.height / 2 : py
        root._localThemeAnimation = true
        if (App && App.theme && App.theme.setRippleOrigin)
            App.theme.setRippleOrigin(cx, cy)
        transitionLayer.play(cx, cy, nextMode)
        NativeHost.changeThemeWithRipple(nextMode, cx, cy)
    }

    function syncNativeHitTestMetrics() {
        if (typeof NativeHost === "undefined" || !NativeHost || !NativeHost.setTitleBarHitTestMetrics)
            return
        NativeHost.setTitleBarHitTestMetrics(
            Math.round(titleBar.nativeTitleBarHeight),
            Math.round(titleBar.nativeCaptionLeftA),
            Math.round(titleBar.nativeCaptionRightA),
            Math.round(titleBar.nativeCaptionLeftB),
            Math.round(titleBar.nativeCaptionRightB)
        )
    }

    function adjustFontScaleByWheel(deltaY) {
        if (typeof App === "undefined" || !App || !App.theme)
            return
        if (deltaY > 0)
            App.theme.increaseFontScale()
        else if (deltaY < 0)
            App.theme.decreaseFontScale()
    }

    Rectangle {
        id: background
        anchors.fill: frameRoot
        radius: root.cornerRadius
        antialiasing: true
        color: Core.Theme.color.surface
        border.color: root.nativeMaximized ? "transparent" : Core.Theme.color.outline
        border.width: root.nativeMaximized ? 0 : root.stableHairline
        z: 0.5
        Behavior on color { ColorAnimation { duration: 150; easing.type: Easing.OutCubic } }
        Behavior on radius { NumberAnimation { duration: 80; easing.type: Easing.OutCubic } }
    }

    ShadowWindow {
        id: customShadow
        targetWindow: null
        targetX: (typeof NativeHost !== "undefined" && NativeHost) ? NativeHost.shadowX : 0
        targetY: (typeof NativeHost !== "undefined" && NativeHost) ? NativeHost.shadowY : 0
        targetWidth: (typeof NativeHost !== "undefined" && NativeHost) ? NativeHost.shadowWidth : 0
        targetHeight: (typeof NativeHost !== "undefined" && NativeHost) ? NativeHost.shadowHeight : 0
        stackController: (typeof App !== "undefined" && App && App.window) ? App.window : null
        shadowEnabled: false
        cornerRadius: root.cornerRadius
    }

    BorderImage {
        id: inlineShadow
        anchors.fill: parent
        visible: root.inlineShadowVisible || opacity > 0.001
        source: "../resources/images/window_shadow.png"
        border.left: root.shadowVisualInset
        border.top: root.shadowVisualInset
        border.right: root.shadowVisualInset
        border.bottom: root.shadowVisualInset
        horizontalTileMode: BorderImage.Stretch
        verticalTileMode: BorderImage.Stretch
        smooth: false
        cache: true
        opacity: root.inlineShadowVisible ? (Core.Theme.mode === "dark" ? 1.0 : 0.78) : 0
        z: 0
        Behavior on opacity {
            NumberAnimation {
                duration: root.inlineShadowVisible ? 2000 : 0
                easing.type: Easing.OutCubic
            }
        }
    }

    WheelHandler {
        acceptedModifiers: Qt.ControlModifier
        target: null
        onWheel: function(event) {
            root.adjustFontScaleByWheel(event.angleDelta.y)
            event.accepted = true
        }
    }

    Item {
        id: frameRoot
        anchors.fill: parent
        anchors.margins: root.shadowVisualInset
        clip: true
        z: 1

        ThemeTransitionLayer {
            id: transitionLayer
            anchors.fill: parent
            radius: root.cornerRadius
            z: 1
        }

        Item {
            id: mainColumn
            anchors.fill: parent
            z: 2

            TitleBar {
                id: titleBar
                y: 0
                z: 2
                width: parent.width
                height: Core.Theme.metrics.titleBarHeight
                windowTitle: Core.AppInfo.windowTitle
                frameRadius: root.cornerRadius
                alwaysOnTop: (typeof NativeHost !== "undefined" && NativeHost) ? NativeHost.alwaysOnTop : false
                showNavToggle: true
                showColorButton: Core.Theme.showColorButton
                windowMaximized: root.nativeMaximized
                useNativeCaption: Qt.platform.os === "windows"
                leftMenus: Core.AppInfo.mainMenus

                onActivateRequested: NativeHost.activateHost()
                onMoveRequested: function(localX, localY) { NativeHost.activateHost(); NativeHost.beginSystemMove(localX, localY) }
                onMoveUpdated: NativeHost.updateSystemMove()
                onMoveFinished: NativeHost.endSystemMove()
                onToggleMaximizeRequested: NativeHost.toggleMaximized()
                onMinimizeRequested: NativeHost.showMinimizedNative()
                onCloseRequested: NativeHost.closeWindow()
                onThemeToggleRequested: function(localPos, nextMode) { root.changeThemeWithRipple(nextMode, localPos.x, localPos.y) }
                onAlwaysOnTopRequested: function(enabled) { NativeHost.setAlwaysOnTop(enabled) }
                onToggleNavRequested: sideNav.toggle()
                onNativeTitleBarHeightChanged: Qt.callLater(root.syncNativeHitTestMetrics)
                onNativeCaptionLeftAChanged: Qt.callLater(root.syncNativeHitTestMetrics)
                onNativeCaptionRightAChanged: Qt.callLater(root.syncNativeHitTestMetrics)
                onNativeCaptionLeftBChanged: Qt.callLater(root.syncNativeHitTestMetrics)
                onNativeCaptionRightBChanged: Qt.callLater(root.syncNativeHitTestMetrics)
                onMenuActionRequested: function(action, kind) {
                    if (kind === "page") {
                        sideNav.restore()
                        sideNav.currentPage = action
                    } else {
                        if (App && App.dialogs)
                            App.dialogs.openChild(NativeHost, action, ({}))
                    }
                }
            }

            Row {
                id: mainRow
                y: titleBar.height
                z: 1
                width: parent.width
                height: Math.max(0, parent.height - titleBar.height)

                ResizableSideNav {
                    id: sideNav
                    height: parent.height
                    width: root.snapToPhysicalPixel((typeof App !== "undefined" && App && App.settings) ? Math.max(0, Math.min(App.settings.valueOr("layout/navWidth", Core.Theme.metrics.navWidthDefault), Core.Theme.metrics.navWidthMax)) : Core.Theme.metrics.navWidthDefault)
                    cornerRadius: root.cornerRadius
                    onCurrentPageChanged: pageHost.showPage(currentPage)
                }

                PageHost {
                    id: pageHost
                    width: parent.width - sideNav.width
                    height: parent.height
                }
            }
        }

        Rectangle {
            id: windowEdgeOverlay
            anchors.fill: parent
            z: 90
            radius: root.cornerRadius
            color: "transparent"
            border.color: root.cornerRadius > 0 ? Core.Theme.color.windowEdge : "transparent"
            border.width: root.cornerRadius > 0 ? root.stableHairline : 0
            antialiasing: true
        }

        ListModel { id: toastModel }
        Repeater {
            model: toastModel
            delegate: Toast {
                z: 1000000
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.bottom: parent.bottom
                anchors.bottomMargin: Core.Theme.dp(22) + index * (Core.Theme.dp(42) + Core.Theme.dp(8))
                height: Core.Theme.dp(42)
                text: model.message
                Component.onCompleted: show(model.message)
                onExpired: {
                    if (index >= 0 && index < toastModel.count)
                        toastModel.remove(index)
                }
            }
        }

    }

    SnapPreviewWindow {
        id: snapPreview
        transientParent: root.Window.window
    }

    Binding { target: titleBar; property: "navHidden"; value: sideNav.width === 0 }

    onWidthChanged: Qt.callLater(root.syncNativeHitTestMetrics)

    Connections {
        target: NativeHost
        function onToastRequested(message) { root.showToast(message) }
        function onMaximizedChanged() {
            root.nativeMaximized = NativeHost.isMaximizedState()
            root.nativeSnapped = NativeHost.isSnappedState()
            if (root.nativeMaximized || root.nativeSnapped)
                root.snapShadowSuppressed = false
        }
        function onGeometryChanged() {
            root.nativeSnapped = NativeHost.isSnappedState()
            if (root.nativeSnapped)
                root.snapShadowSuppressed = false
        }
        function onCaptionPressed() {
            titleBar.closeMenus()
            customShadow.forceStackSync(1)
        }
        function onSnapPreviewChanged(key, x, y, w, h, visible) {
            if (key !== root.windowKey)
                return
            if (visible)
                snapPreview.showAt(Qt.rect(x, y, w, h))
            else
                snapPreview.hidePreview()
        }
    }

    Connections {
        target: App && App.theme ? App.theme : null
        function onModeChanged(mode) {
            if (root._localThemeAnimation) {
                root._localThemeAnimation = false
                return
            }
            transitionLayer.play(frameRoot.width / 2, frameRoot.height / 2, mode)
        }
    }

    Connections {
        target: (typeof App !== "undefined" && App && App.tray) ? App.tray : null
        function onTrayPrimaryClicked() {
            if (App && App.tray)
                App.tray.centerMainWindow()
        }
    }

    Component.onCompleted: {
        root.nativeMaximized = NativeHost.isMaximizedState()
        root.nativeSnapped = NativeHost.isSnappedState()
        if (App && App.tray)
            App.tray.registerWindow(NativeHost)
        Qt.callLater(root.syncNativeHitTestMetrics)
    }
}

