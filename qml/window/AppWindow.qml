import QtQuick
import QtQuick.Window
import QtQuick.Controls
import FramelessNative 1.0
import "../core" as Core
import "../controls"

Window {
    id: root

    readonly property real devicePixelRatio: Math.max(1.0, (root.screen ? root.screen.devicePixelRatio : Screen.devicePixelRatio))
    readonly property real physicalPixel: 1.0 / devicePixelRatio
    readonly property real stableHairline: Math.max(1.0, physicalPixel)

    default property alias content: contentHost.data
    property var bridge
    property string windowKey: "window"
    property alias titleBar: titleBarControl
    property alias leftMenus: titleBarControl.leftMenus
    property string shadowPolicy: "auto"
    property string cornerPolicy: "auto"
    property bool alwaysOnTop: false
    property bool showNavToggle: true
    property bool showColorButton: Core.Theme.showColorButton
    property bool showThemeButton: true
    property bool showPinButton: true
    property bool lowMemoryVisuals: root.windowKey !== "main"
    property bool autoRestoreWindowState: true
    property bool autoShow: true
    property bool snappedVisual: false
    property bool nativeChromeRegistered: false
    property bool windowMaximized: false
    property string effectiveShadowPolicy: shadowPolicy === "auto"
                                           && root.bridge && root.bridge.window
                                           && root.bridge.window.windowShadowPolicy !== undefined
                                           ? root.bridge.window.windowShadowPolicy
                                           : shadowPolicy
    property string effectiveCornerPolicy: cornerPolicy === "auto"
                                           && root.bridge && root.bridge.window
                                           && root.bridge.window.windowCornerPolicy !== undefined
                                           ? root.bridge.window.windowCornerPolicy
                                           : cornerPolicy
    property bool customExternalShadow: effectiveShadowPolicy === "custom-external"
                                        && root.bridge && root.bridge.window
                                        && root.bridge.window.externalShadowSupported
                                        && !root.nativeShadowDisabledForDiagnostics()
    property bool nativeClippedCustomShell: customExternalShadow && Qt.platform.os === "windows"
    property bool nativeExternalShadow: customExternalShadow && Qt.platform.os === "windows"
    property bool qmlExternalShadow: customExternalShadow && !nativeExternalShadow
    property bool nativeShadowDisplayReady: false
    property bool customShadowEnabled: customExternalShadow
                                        && root.nativeShadowDisplayReady
                                        && root.visible
                                        && root.visibility !== Window.Minimized
                                        && !root.windowMaximized
                                        && !root.snappedVisual
    property int externalShadowMargin: {
        const metrics = Core.Theme.metrics
        if (metrics && metrics["windowShadowMargin"] !== undefined)
            return Math.max(0, Math.round(metrics["windowShadowMargin"]))
        if (metrics && metrics["shadowMargin"] !== undefined)
            return Math.max(0, Math.round(metrics["shadowMargin"]))
        return Core.Theme.dp(38)
    }
    property real externalShadowOpacity: {
        const metrics = Core.Theme.metrics
        if (Core.Theme.mode === "dark" && metrics && metrics["windowShadowOpacityDark"] !== undefined)
            return Math.max(0, Math.min(1, Number(metrics["windowShadowOpacityDark"])))
        if (Core.Theme.mode !== "dark" && metrics && metrics["windowShadowOpacityLight"] !== undefined)
            return Math.max(0, Math.min(1, Number(metrics["windowShadowOpacityLight"])))
        return Core.Theme.mode === "dark" ? 1.0 : 1.0
    }
    property int normalCornerRadius: Core.Theme.radius.window
    property int cornerRadius: (root.windowMaximized || root.snappedVisual || effectiveCornerPolicy === "square") ? 0 : normalCornerRadius
    property bool _localThemeAnimation: false
    property bool _childCloseScheduled: false
    property string pendingTransitionMode: ""
    property real pendingTransitionX: 0
    property real pendingTransitionY: 0

    signal windowEvent(string type, var payload)
    signal requestThemeToggle(point localPos, string nextMode)
    signal requestAlwaysOnTop(bool enabled)
    signal navToggleRequested()
    flags: Qt.Window
           | Qt.FramelessWindowHint
           | Qt.NoDropShadowWindowHint
           | Qt.WindowSystemMenuHint
           | Qt.WindowMinimizeButtonHint
           | Qt.WindowMaximizeButtonHint
           | Qt.WindowCloseButtonHint
    color: Qt.platform.os === "windows" ? Core.Theme.color.surface : "transparent"
    visible: false

    Component.onCompleted: {
        if (root.windowKey.indexOf("child-") === 0) {
            root.persistentSceneGraph = false
            root.persistentGraphics = false
        }
        root.registerNativeChrome()
        if (root.autoRestoreWindowState)
            root.restorePersistedWindowState()
        if (root.autoShow) {
            root.visible = true
            root.syncNativeWindowState()
        }
    }

    NativeWindowAgent {
        id: nativeAgent
    }

    ExternalShadowController {
        id: externalShadow
    }

    ShadowWindow {
        id: customShadow
        targetWindow: (root.qmlExternalShadow && root.customShadowEnabled) ? root : null
        stackController: externalShadow
        shadowEnabled: root.qmlExternalShadow && root.customShadowEnabled
        shadowMargin: root.externalShadowMargin
        cornerRadius: root.cornerRadius
    }

    function raiseSelf() {
        try { root.raise() } catch (e) {}
        try { root.requestActivate() } catch (e2) {}
    }

    function registerNativeChrome() {
        nativeAgent.setup(root)
        nativeAgent.setShellBackgroundColor(Core.Theme.color.surface)
        nativeAgent.setFastExitOnClose(root.windowKey === "main")
        root.nativeChromeRegistered = true
        nativeAgent.setCustomShadowEnabled(root.customExternalShadow)
        nativeAgent.setCornerRadius(root.cornerRadius)
        nativeAgent.setShadowAsset(Qt.resolvedUrl("../../resources/images/window_shadow.png"), root.externalShadowMargin,
                                   root.externalShadowOpacity)

        nativeAgent.setTitleBar(titleBarControl)
        nativeAgent.setSystemButton("minimize", titleBarControl.minimizeButtonItem)
        nativeAgent.setSystemButton("maximize", titleBarControl.maximizeButtonItem)
        nativeAgent.setSystemButton("close", titleBarControl.closeButtonItem)

        const clickableItems = [
            titleBarControl.navToggleButtonItem,
            titleBarControl.leftMenusAreaItem,
            titleBarControl.paletteButtonItem,
            titleBarControl.themeButtonItem,
            titleBarControl.pinButtonItem,
            titleBarControl.minimizeButtonItem,
            titleBarControl.maximizeButtonItem,
            titleBarControl.closeButtonItem
        ]
        for (let i = 0; i < clickableItems.length; ++i) {
            if (clickableItems[i])
                nativeAgent.setHitTestVisible(clickableItems[i], true)
        }
    }

    function nativeShadowDisabledForDiagnostics() {
        if (typeof App === "undefined" || !App || !App.envValue)
            return false
        const value = String(App.envValue("QROUNDEDFRAME_DISABLE_NATIVE_SHADOW") || "").toLowerCase()
        return value === "1" || value === "true" || value === "yes" || value === "on"
    }

    function registerNativeClickableItem(item) {
        if (root.nativeChromeRegistered && item)
            nativeAgent.setHitTestVisible(item, true)
    }

    function unregisterNativeClickableItem(item) {
        if (root.nativeChromeRegistered && item)
            nativeAgent.setHitTestVisible(item, false)
    }

    function cleanupExternalShadow() {
        try {
            if (externalShadow && externalShadow.destroyNativeShadow)
                externalShadow.destroyNativeShadow(root)
        } catch (e) {}
        try {
            customShadow.targetWindow = null
            customShadow.shadowEnabled = false
        } catch (e2) {}
    }

    function finalizeChildClose() {
        if (root._childCloseScheduled)
            return
        root._childCloseScheduled = true
        Qt.callLater(function() {
            if (root.bridge && root.bridge.window && root.bridge.window.saveNativeManagedWindowState)
                root.bridge.window.saveNativeManagedWindowState(root)
            root.visible = false
            root.releaseResources()
            root.cleanupExternalShadow()
            if (root.releaseContent)
                root.releaseContent()
            root.windowEvent("closing", ({}))
        })
    }

    function requestCloseFromController() {
        if (root.windowKey.indexOf("child-") === 0) {
            root.finalizeChildClose()
            return
        }
        root.close()
    }
    function syncExternalShadow() {
        if (!externalShadow || !externalShadow.setNativeShadow)
            return
        if (root.nativeExternalShadow) {
            externalShadow.setNativeShadow(root, root.customShadowEnabled,
                                           Qt.resolvedUrl("../../resources/images/window_shadow.png"),
                                           root.externalShadowMargin,
                                           root.externalShadowOpacity,
                                           root.cornerRadius)
        } else {
            externalShadow.destroyNativeShadow(root)
        }
    }

    function scheduleNativeShadowShow() {
        root.syncExternalShadow()
        stableNativeShadowSyncTimer.restart()
        Qt.callLater(function() {
            root.syncNativeWindowState()
            if (root.nativeExternalShadow && root.customShadowEnabled)
                externalShadow.syncNativeShadow(root)
        })
    }
    function markNativeShadowDisplayReady() {
        if (!root.visible || root.nativeShadowDisplayReady)
            return
        root.nativeShadowDisplayReady = true
        root.scheduleNativeShadowShow()
    }
    function syncNativeWindowState() {
        root.windowMaximized = root.visibility === Window.Maximized
                               || root.visibility === Window.FullScreen
                               || nativeAgent.isMaximized(root)
        root.snappedVisual = root.bridge && root.bridge.window && root.bridge.window.isSnappedState
                             ? root.bridge.window.isSnappedState(root)
                             : externalShadow.isSnapped(root)
        root.syncExternalShadow()
    }

    function toggleMaximized() {
        nativeAgent.toggleMaximized(root)
    }

    function changeThemeWithRipple(nextMode, px, py) {
        if (!root.bridge || !root.bridge.theme)
            return
        if (nextMode !== "dark" && nextMode !== "light")
            return
        if (nextMode === Core.Theme.mode)
            return
        const cx = px === undefined ? frameRoot.width / 2 : px
        const cy = py === undefined ? frameRoot.height / 2 : py
        root._localThemeAnimation = true
        if (root.bridge.theme.setRippleOrigin)
            root.bridge.theme.setRippleOrigin(cx, cy)
        root.playTransition(cx, cy, nextMode)
        root.bridge.theme.setMode(nextMode)
        root.requestThemeToggle(Qt.point(cx, cy), nextMode)
    }

    function playTransition(cx, cy, mode) {
        if (root.lowMemoryVisuals)
            return
        pendingTransitionX = cx
        pendingTransitionY = cy
        pendingTransitionMode = mode
        if (transitionLayerLoader.item) {
            transitionLayerLoader.item.play(pendingTransitionX, pendingTransitionY, pendingTransitionMode)
        } else {
            transitionLayerLoader.active = true
        }
    }

    function adjustFontScaleByWheel(deltaY) {
        if (!root.bridge || !root.bridge.theme)
            return
        if (deltaY > 0)
            root.bridge.theme.increaseFontScale()
        else if (deltaY < 0)
            root.bridge.theme.decreaseFontScale()
    }

    function restorePersistedWindowState() {
        if (root.bridge && root.bridge.window && root.bridge.window.restoreNativeManagedWindowState)
            root.bridge.window.restoreNativeManagedWindowState(root)
    }

    function showToast(message) {
        toastModel.append({ "message": message, "createdAt": Date.now() })
        while (toastModel.count > 5)
            toastModel.remove(0)
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
        objectName: "appFrameRoot"
        property int visualRadius: root.cornerRadius
        anchors.fill: parent
        clip: true

        Rectangle {
            id: background
            anchors.fill: parent
            radius: root.cornerRadius
            antialiasing: true
            color: Core.Theme.color.surface
            border.color: "transparent"
            border.width: 0
            Behavior on color { ColorAnimation { duration: Core.Theme.animatedColorTransitionMs; easing.type: Easing.InOutCubic } }
            Behavior on radius { NumberAnimation { duration: 80; easing.type: Easing.OutCubic } }
        }

        Loader {
            id: transitionLayerLoader
            anchors.fill: parent
            z: 1
            active: false
            sourceComponent: ThemeTransitionLayer {
                radius: root.cornerRadius
                onFinished: {
                    transitionLayerLoader.active = false
                    if (root.windowKey === "main" && root.bridge && root.bridge.trimMemoryNow)
                        Qt.callLater(root.bridge.trimMemoryNow)
                }
            }
            onLoaded: {
                if (item && root.pendingTransitionMode.length > 0)
                    item.play(root.pendingTransitionX, root.pendingTransitionY, root.pendingTransitionMode)
            }
        }

        Item {
            id: mainColumn
            anchors.fill: parent
            z: 2

            TitleBar {
                id: titleBarControl
                y: 0
                z: 2
                width: parent.width
                height: Core.Theme.metrics.titleBarHeight
                windowTitle: root.title.length > 0 ? root.title : Core.AppInfo.windowTitle
                frameRadius: root.cornerRadius
                alwaysOnTop: root.alwaysOnTop
                showNavToggle: root.showNavToggle
                showColorButton: root.showColorButton
                showThemeButton: root.showThemeButton
                showPinButton: root.showPinButton
                windowMaximized: root.windowMaximized
                useNativeCaption: true

                onActivateRequested: {
                    root.raiseSelf()
                    if (root.qmlExternalShadow)
                        customShadow.forceStackSync(1)
                    else if (root.nativeShadowDisplayReady)
                        externalShadow.syncNativeShadow(root)
                }

                onToggleMaximizeRequested: root.toggleMaximized()
                onMinimizeRequested: root.showMinimized()
                onCloseRequested: {
                    if (root.windowKey === "main" && typeof App !== "undefined" && App && App.exitApplication)
                        App.exitApplication()
                    else if (root.windowKey.indexOf("child-") === 0)
                        root.finalizeChildClose()
                    else
                        root.close()
                }
                onThemeToggleRequested: function(localPos, nextMode) {
                    root.changeThemeWithRipple(nextMode, localPos.x, localPos.y)
                }
                onAlwaysOnTopRequested: function(enabled) {
                    root.alwaysOnTop = enabled
                    if (root.bridge && root.bridge.window)
                        root.bridge.window.setAlwaysOnTop(root, enabled)
                    root.requestAlwaysOnTop(enabled)
                }
                onToggleNavRequested: root.navToggleRequested()
            }

            Connections {
                target: titleBarControl
                function onPaletteButtonItemChanged() { root.registerNativeClickableItem(titleBarControl.paletteButtonItem) }
                function onThemeButtonItemChanged() { root.registerNativeClickableItem(titleBarControl.themeButtonItem) }
                function onPinButtonItemChanged() { root.registerNativeClickableItem(titleBarControl.pinButtonItem) }
            }

            Item {
                id: contentHost
                y: titleBarControl.height
                z: 1
                width: parent.width
                height: Math.max(0, parent.height - titleBarControl.height)
                clip: true
            }
        }

        Rectangle {
            id: windowEdgeOverlay
            anchors.fill: parent
            anchors.margins: root.stableHairline
            z: 90
            radius: Math.max(0, root.cornerRadius - root.stableHairline)
            color: "transparent"
            visible: root.cornerRadius > 0
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


    Timer {
        id: stableNativeShadowSyncTimer
        interval: 35
        repeat: false
        onTriggered: {
            root.syncNativeWindowState()
            if (root.nativeExternalShadow && root.customShadowEnabled)
                externalShadow.syncNativeShadow(root)
        }
    }
    Timer {
        id: snapStateSyncTimer
        interval: 0
        repeat: false
        onTriggered: root.syncNativeWindowState()
    }
    Timer {
        id: resizeTrimTimer
        interval: 1000
        repeat: false
        onTriggered: {
            if (root.windowKey === "main" && root.bridge && root.bridge.trimMemory)
                root.bridge.trimMemory()
        }
    }

    Connections {
        target: root.bridge ? root.bridge.theme : null
        function onModeChanged(mode) {
            nativeAgent.setShellBackgroundColor(Core.Theme.color.surface)
            nativeAgent.setShadowAsset(Qt.resolvedUrl("../../resources/images/window_shadow.png"), root.externalShadowMargin,
                                       root.externalShadowOpacity)
            root.syncExternalShadow()
            if (root._localThemeAnimation) {
                root._localThemeAnimation = false
                return
            }
            root.playTransition(frameRoot.width / 2, frameRoot.height / 2, mode)
        }
    }

    Component.onDestruction: root.cleanupExternalShadow()

    onXChanged: { snapStateSyncTimer.restart(); stableNativeShadowSyncTimer.restart() }
    onYChanged: { snapStateSyncTimer.restart(); stableNativeShadowSyncTimer.restart() }
    onWidthChanged: {
        snapStateSyncTimer.restart()
        stableNativeShadowSyncTimer.restart()
        if (root.windowKey === "main")
            resizeTrimTimer.restart()
        windowEvent("widthChanged", ({ "width": width }))
    }
    onHeightChanged: {
        snapStateSyncTimer.restart()
        stableNativeShadowSyncTimer.restart()
        if (root.windowKey === "main")
            resizeTrimTimer.restart()
        windowEvent("heightChanged", ({ "height": height }))
    }
    onVisibilityChanged: {
        root.syncNativeWindowState()
        snapStateSyncTimer.restart()
        windowEvent("visibilityChanged", ({ "visibility": root.visibility }))
        nativeAgent.setCornerRadius(root.cornerRadius)
        root.scheduleNativeShadowShow()
    }
    onVisibleChanged: {
        if (!root.visible)
            root.nativeShadowDisplayReady = false
        root.scheduleNativeShadowShow()
    }
    onFrameSwapped: {
        root.markNativeShadowDisplayReady()
    }
    onCornerRadiusChanged: {
        nativeAgent.setCornerRadius(root.cornerRadius)
        root.syncExternalShadow()
    }
    onCustomExternalShadowChanged: {
        nativeAgent.setCustomShadowEnabled(root.customExternalShadow)
        root.syncExternalShadow()
    }
    onCustomShadowEnabledChanged: root.syncExternalShadow()
    onShowColorButtonChanged: {
        if (!root.showColorButton)
            root.unregisterNativeClickableItem(titleBarControl.paletteButtonItem)
    }
    onShowThemeButtonChanged: {
        if (!root.showThemeButton)
            root.unregisterNativeClickableItem(titleBarControl.themeButtonItem)
    }
    onShowPinButtonChanged: {
        if (!root.showPinButton)
            root.unregisterNativeClickableItem(titleBarControl.pinButtonItem)
    }
    onAlwaysOnTopChanged: {
        if (root.nativeExternalShadow) {
            root.syncExternalShadow()
            if (root.customShadowEnabled)
                externalShadow.syncNativeShadow(root)
        } else if (root.qmlExternalShadow) {
            customShadow.forceStackSync(3)
        }
    }
    onEffectiveShadowPolicyChanged: {
        nativeAgent.setCustomShadowEnabled(root.customExternalShadow)
        root.syncExternalShadow()
    }
    onExternalShadowMarginChanged: {
        nativeAgent.setShadowAsset(Qt.resolvedUrl("../../resources/images/window_shadow.png"), root.externalShadowMargin,
                                   root.externalShadowOpacity)
        root.syncExternalShadow()
    }
    onExternalShadowOpacityChanged: {
        nativeAgent.setShadowAsset(Qt.resolvedUrl("../../resources/images/window_shadow.png"), root.externalShadowMargin,
                                   root.externalShadowOpacity)
        root.syncExternalShadow()
    }
    onActiveChanged: {
        windowEvent("activeChanged", ({ "active": active }))
        if (active && root.nativeExternalShadow && root.nativeShadowDisplayReady) {
            root.syncExternalShadow()
            if (root.customShadowEnabled)
                externalShadow.syncNativeShadow(root)
        }
    }
    onClosing: function(close) {
        if (root.windowKey === "main" && typeof App !== "undefined" && App && App.exitApplication) {
            close.accepted = false
            App.exitApplication()
            return
        }
        if (root.windowKey.indexOf("child-") === 0 && typeof App !== "undefined" && App && App.dialogs && App.dialogs.closeChildWindow) {
            close.accepted = true
            root.finalizeChildClose()
            return
        }
        close.accepted = true
    }
}







