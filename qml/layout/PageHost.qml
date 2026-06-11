import QtQuick
import "../core" as Core

Item {
    id: root
    property string currentPage: "home"
    property string pendingPage: ""
    property string loadedPage: ""

    function sourceFor(page) {
        return Core.AppInfo.pageSource(page)
    }

    function logRuntime(message) {
        if (typeof App !== "undefined" && App && App.logRuntime)
            App.logRuntime(message)
    }

    function showPage(page) {
        if (page === currentPage && pageLoader.active)
            return
        pendingPage = page
        // Unload the old source before loading a new page so page-owned
        // Image/Canvas items can be destroyed. Qt may still keep warm
        // component/font/texture caches; use page unloaded logs for lifecycle.
        if (loadedPage.length > 0)
            root.logRuntime("page unloading key=" + loadedPage)
        pageLoader.active = false
        pageLoader.source = ""
        reloadTimer.restart()
    }

    Loader {
        id: pageLoader
        anchors.fill: parent
        asynchronous: root.currentPage !== "home"
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
        }
    }

    Timer {
        id: reloadTimer
        interval: 0
        repeat: false
        onTriggered: {
            root.currentPage = root.pendingPage.length > 0 ? root.pendingPage : "home"
            pageLoader.source = root.sourceFor(root.currentPage)
            pageLoader.active = true
            if (typeof App !== "undefined" && App && App.logMemorySample)
                Qt.callLater(function() { App.logMemorySample("page_" + root.currentPage) })
            trimTimer.restart()
        }
    }

    Timer {
        id: trimTimer
        interval: 260
        repeat: false
        onTriggered: {
            if (typeof App !== "undefined" && App && App.trimMemory)
                App.trimMemory()
        }
    }
}
