#pragma once

#include <QtCore/QEvent>
#include <QtCore/QAbstractNativeEventFilter>
#include <QtCore/QObject>
#include <QtCore/QPointer>
#include <QtCore/QSize>
#include <QtCore/QUrl>
#include <QtGui/QColor>
#include <QtQml/qqmlregistration.h>
#include <QtQuick/QQuickItem>
#include <QtQuick/QQuickWindow>

#include <QWKQuick/quickwindowagent.h>

class NativeWindowAgent : public QWK::QuickWindowAgent, public QAbstractNativeEventFilter {
    Q_OBJECT
    QML_ELEMENT

public:
    explicit NativeWindowAgent(QObject *parent = nullptr);
    ~NativeWindowAgent() override;

    Q_INVOKABLE void setup(QQuickWindow *window);
    Q_INVOKABLE void setTitleBar(QQuickItem *item);
    Q_INVOKABLE void setSystemButton(const QString &role, QQuickItem *item);
    Q_INVOKABLE void setHitTestVisible(QQuickItem *item, bool visible);
    Q_INVOKABLE void setCustomShadowEnabled(bool enabled);
    Q_INVOKABLE void setCornerRadius(int radius);
    Q_INVOKABLE void setShadowAsset(const QUrl &source, int margin, qreal opacity);
    Q_INVOKABLE void setShellBackgroundColor(const QColor &color);
    Q_INVOKABLE void setResizeHitTestInsets(int edgeInset, int cornerInset);
    Q_INVOKABLE void setFastExitOnClose(bool enabled);
    Q_INVOKABLE bool isMaximized(QQuickWindow *window) const;
    Q_INVOKABLE void toggleMaximized(QQuickWindow *window);

protected:
    bool eventFilter(QObject *watched, QEvent *event) override;
    bool nativeEventFilter(const QByteArray &eventType, void *message, qintptr *result) override;

private:
    static int systemButtonRole(const QString &role);
    void applyWindowAttributes();
    void applyWindowRegion(bool redraw = true);
    void applyWindowRegionForNativeSize(int width, int height, bool redraw = false);
    void clearWindowRegion();
    void installNativeShellFilter();
    void uninstallNativeShellFilter();
    void updateClassBackgroundBrush();
    void restoreClassBackgroundBrush();
    int nativeSystemButtonHitTest(qintptr lParam) const;
    bool nativeItemContainsScreenPoint(QQuickItem *item, qintptr lParam) const;
    QColor shellBackgroundColor() const;

    QPointer<QQuickWindow> m_window;
    QPointer<QQuickItem> m_titleBarItem;
    QPointer<QQuickItem> m_minimizeButton;
    QPointer<QQuickItem> m_maximizeButton;
    QPointer<QQuickItem> m_closeButton;
    bool m_customShadow = false;
    bool m_nativeShellFilterInstalled = false;
    quintptr m_backgroundBrush = 0;
    quintptr m_previousClassBackgroundBrush = 0;
    int m_cornerRadius = 0;
    QSize m_lastRegionSize;
    int m_lastRegionRadius = -1;
    int m_resizeEdgeInset = 4;
    int m_resizeCornerInset = 6;
    bool m_fastExitOnClose = false;
    QColor m_shellBackgroundColor;
    QUrl m_shadowSource;
    int m_shadowMargin = 0;
    qreal m_shadowOpacity = 1.0;
};
