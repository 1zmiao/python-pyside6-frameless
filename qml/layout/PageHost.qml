import QtQuick
import "../core" as Core

Item {
    id: root
    property string currentPage: "home"
    property string pendingPage: ""
    property string loadedPage: ""
    property var warmedComponents: ({})
    property var warmedOrder: []
    readonly property int maxPreparedPages: {
        if (typeof App !== "undefined" && App && App.performance && App.performance.effectiveProfile === "low-memory")
            return 1
        return 2
    }

    function sourceFor(page) {
        return Core.AppInfo.pageSource(page)
    }

    function logRuntime(message) {
        if (typeof App !== "undefined" && App && App.logRuntime)
            App.logRuntime(message)
    }

    function preparePage(page) {
        page = String(page || "")
        if (page.length <= 0 || page === currentPage || warmedComponents[page])
            return
        const source = root.sourceFor(page)
        if (!source || source.length <= 0)
            return
        root.evictPreparedPages(page)
        const component = Qt.createComponent(source, Component.Asynchronous)
        warmedComponents[page] = component
        warmedOrder = warmedOrder.concat([page])
        component.statusChanged.connect(function() {
            if (component.status === Component.Ready)
                root.logRuntime("page prepared key=" + page)
            else if (component.status === Component.Error)
                root.logRuntime("page prepare failed key=" + page + " error=" + component.errorString())
        })
    }

    function evictPreparedPages(nextPage) {
        while (warmedOrder.length >= maxPreparedPages) {
            const page = warmedOrder[0]
            warmedOrder = warmedOrder.slice(1)
            if (page === currentPage || page === nextPage)
                continue
            const component = warmedComponents[page]
            delete warmedComponents[page]
            if (component && component.destroy)
                component.destroy()
            root.logRuntime("page prepared cache evicted key=" + page)
            return
        }
    }

    function showPage(page) {
        if (page === currentPage && pageLoader.active)
            return
        pendingPage = page
        if (loadedPage.length > 0)
            root.logRuntime("page unloading key=" + loadedPage)
        root.currentPage = pendingPage.length > 0 ? pendingPage : "home"
        pageLoader.source = root.sourceFor(root.currentPage)
        pageLoader.active = true
        if (typeof App !== "undefined" && App && App.logMemorySample)
            Qt.callLater(function() { App.logMemorySample("page_" + root.currentPage) })
    }

    Loader {
        id: pageLoader
        anchors.fill: parent
        asynchronous: false
        active: true
        source: root.sourceFor(root.currentPage)
        onItemChanged: {
            if (!item && root.loadedPage.length > 0) {
                root.logRuntime("page unloaded key=" + root.loadedPage)
                root.loadedPage = ""
            }
        }
        onLoaded: {
            root.loadedPage = root.currentPage
            root.logRuntime("page loaded key=" + root.currentPage + " source=" + String(source))
            settledTrimTimer.restart()
        }
    }

    Timer {
        id: settledTrimTimer
        interval: 1800
        repeat: false
        onTriggered: {
            if (typeof App !== "undefined" && App && App.trimMemoryAfterPageSettled)
                App.trimMemoryAfterPageSettled()
        }
    }
}
