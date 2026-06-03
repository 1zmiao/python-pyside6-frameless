import QtQuick

Item {
    id: root
    property string currentPage: "home"
    property string pendingPage: ""

    function sourceFor(page) {
        if (page === "settings") return "../pages/SettingsPage.qml"
        if (page === "tools") return "../pages/ToolsPage.qml"
        if (page === "update") return "../pages/UpdatePage.qml"
        if (page === "about") return "../pages/AboutPage.qml"
        return "../pages/HomePage.qml"
    }

    function showPage(page) {
        if (page === currentPage && pageLoader.active)
            return
        pendingPage = page
        pageLoader.active = false
        reloadTimer.restart()
    }

    Loader {
        id: pageLoader
        anchors.fill: parent
        asynchronous: root.currentPage !== "home"
        active: true
        source: root.sourceFor(root.currentPage)
    }

    Timer {
        id: reloadTimer
        interval: 0
        repeat: false
        onTriggered: {
            root.currentPage = root.pendingPage.length > 0 ? root.pendingPage : "home"
            pageLoader.source = root.sourceFor(root.currentPage)
            pageLoader.active = true
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
