#include "native_inline_drag_area.h"

#include <QtCore/QMetaObject>
#include <QtCore/QEvent>
#include <QtCore/QtGlobal>
#include <QtCore/QVariant>
#include <QtGui/QGuiApplication>
#include <QtGui/QMouseEvent>
#include <QtQuick/QQuickWindow>

#include <cmath>
#include <limits>

#ifdef Q_OS_WIN
#    ifndef NOMINMAX
#        define NOMINMAX
#    endif
#    include <windows.h>
#endif

namespace {
qreal snapToPhysicalPixel(qreal value, QQuickWindow *window) {
    const qreal dpr = window ? window->effectiveDevicePixelRatio() : 1.0;
    if (dpr <= 0.0)
        return value;
    return std::round(value * dpr) / dpr;
}

bool isLeftButtonPhysicallyDown() {
#ifdef Q_OS_WIN
    return (GetAsyncKeyState(VK_LBUTTON) & 0x8000) != 0;
#else
    return (QGuiApplication::mouseButtons() & Qt::LeftButton) != Qt::NoButton;
#endif
}

}

NativeInlineDragArea::NativeInlineDragArea(QQuickItem *parent)
    : QQuickItem(parent) {
    setAcceptedMouseButtons(Qt::LeftButton);
    setFlag(QQuickItem::ItemHasContents, false);
}

QQuickItem *NativeInlineDragArea::target() const {
    return m_configuredTarget;
}

void NativeInlineDragArea::setTarget(QQuickItem *value) {
    if (m_configuredTarget == value)
        return;
    m_configuredTarget = value;
    emit targetChanged();
}

qreal NativeInlineDragArea::titleBarHeight() const {
    return m_titleBarHeight;
}

void NativeInlineDragArea::setTitleBarHeight(qreal value) {
    if (qFuzzyCompare(m_titleBarHeight, value))
        return;
    m_titleBarHeight = value;
    emit titleBarHeightChanged();
}

qreal NativeInlineDragArea::controlsReserve() const {
    return m_controlsReserve;
}

void NativeInlineDragArea::setControlsReserve(qreal value) {
    if (qFuzzyCompare(m_controlsReserve, value))
        return;
    m_controlsReserve = value;
    emit controlsReserveChanged();
}

qreal NativeInlineDragArea::edgeResizeReserve() const {
    return m_edgeResizeReserve;
}

void NativeInlineDragArea::setEdgeResizeReserve(qreal value) {
    if (qFuzzyCompare(m_edgeResizeReserve, value))
        return;
    m_edgeResizeReserve = qMax<qreal>(0.0, value);
    emit edgeResizeReserveChanged();
}

QQuickItem *NativeInlineDragArea::topWindowAt(const QPointF &point) const {
    auto *container = parentItem();
    if (!container)
        return nullptr;

    bool hasInlineWindow = false;
    for (auto *item : container->childItems()) {
        if (item && item->property("inlineChildWindow").toBool()) {
            hasInlineWindow = true;
            break;
        }
    }
    if (!hasInlineWindow && container->parentItem())
        container = container->parentItem();

    QQuickItem *top = nullptr;
    QPointF topLocalPoint;
    qreal topZ = -std::numeric_limits<qreal>::infinity();
    const auto children = container->childItems();
    for (auto *item : children) {
        if (!item || item == this || !item->isVisible())
            continue;
        if (!item->property("inlineChildWindow").toBool())
            continue;
        const QPointF localPoint = mapToItem(item, point);
        if (localPoint.x() < 0 || localPoint.x() > item->width())
            continue;
        if (localPoint.y() < 0 || localPoint.y() > item->height())
            continue;
        if (item->z() > topZ) {
            top = item;
            topLocalPoint = localPoint;
            topZ = item->z();
        }
    }
    if (!top)
        return nullptr;
    if (top->property("minimized").toBool())
        return top;
    if (topLocalPoint.y() > m_titleBarHeight)
        return nullptr;
    if (topLocalPoint.x() < m_edgeResizeReserve || topLocalPoint.y() < m_edgeResizeReserve || topLocalPoint.x() > top->width() - m_edgeResizeReserve)
        return nullptr;
    if (topLocalPoint.x() > top->width() - m_controlsReserve)
        return nullptr;
    return top;
}

void NativeInlineDragArea::beginMove(QQuickItem *target, const QPointF &, const QPointF &globalPoint) {
    if (!target)
        return;
    auto *targetParent = target->parentItem();
    if (!targetParent)
        return;
    if (!m_configuredTarget) {
        auto *container = parentItem();
        if (container && container->parentItem())
            container = container->parentItem();
        if (container) {
            QMetaObject::invokeMethod(
                container,
                "raiseWindow",
                Q_ARG(QVariant, target->property("pageKey")));
        }
    }
    m_target = target;
    m_pressGlobal = globalPoint;
    m_startPosition = QPointF(target->x(), target->y());
    m_moved = false;
    target->setProperty("moving", true);
    emit dragStarted();
    if (auto *w = window()) {
        w->installEventFilter(this);
        m_filterInstalled = true;
    }
    setKeepMouseGrab(true);
    grabMouse();
}

void NativeInlineDragArea::endMove(bool releaseGrab) {
    if (m_filterInstalled) {
        if (auto *w = window())
            w->removeEventFilter(this);
        m_filterInstalled = false;
    }
    if (m_target)
        m_target->setProperty("moving", false);
    m_target.clear();
    setKeepMouseGrab(false);
    if (releaseGrab)
        ungrabMouse();
}

void NativeInlineDragArea::updateMove(const QPointF &globalPoint) {
    if (!m_target)
        return;
    auto *parent = m_target->parentItem();
    if (!parent) {
        endMove();
        return;
    }
    const QPointF globalDelta = globalPoint - m_pressGlobal;
    if (!m_moved && (qAbs(globalDelta.x()) + qAbs(globalDelta.y())) < 3.0)
        return;
    m_moved = true;
    m_target->setX(snapToPhysicalPixel(m_startPosition.x() + globalDelta.x(), window()));
    m_target->setY(snapToPhysicalPixel(m_startPosition.y() + globalDelta.y(), window()));
}

void NativeInlineDragArea::finishMoveFromRelease(QMouseEvent *event) {
    if (!m_target)
        return;
    const bool wasMoved = m_moved;
    const QVariant pageKey = m_target->property("pageKey");
    endMove();
    if (!wasMoved) {
        emit clicked();
        emit targetClicked(pageKey);
    }
    if (event)
        event->accept();
}

bool NativeInlineDragArea::eventFilter(QObject *watched, QEvent *event) {
    if (!m_target || watched != window())
        return QQuickItem::eventFilter(watched, event);

    switch (event->type()) {
    case QEvent::MouseMove: {
        auto *mouse = static_cast<QMouseEvent *>(event);
        if (!(mouse->buttons() & Qt::LeftButton) || !isLeftButtonPhysicallyDown()) {
            endMove();
            mouse->accept();
            return true;
        }
        updateMove(mouse->globalPosition());
        mouse->accept();
        return true;
    }
    case QEvent::MouseButtonRelease: {
        auto *mouse = static_cast<QMouseEvent *>(event);
        if (mouse->button() == Qt::LeftButton) {
            finishMoveFromRelease(mouse);
            return true;
        }
        break;
    }
    case QEvent::UngrabMouse:
    case QEvent::GrabMouse:
        break;
    default:
        break;
    }
    return QQuickItem::eventFilter(watched, event);
}

void NativeInlineDragArea::mousePressEvent(QMouseEvent *event) {
    if (!event || event->button() != Qt::LeftButton) {
        if (event)
            event->ignore();
        return;
    }
    auto *target = m_configuredTarget ? m_configuredTarget.data() : topWindowAt(event->position());
    if (!target) {
        event->ignore();
        return;
    }
    beginMove(target, event->scenePosition(), event->globalPosition());
    event->accept();
}

void NativeInlineDragArea::mouseMoveEvent(QMouseEvent *event) {
    if (!event || !m_target) {
        if (event)
            event->ignore();
        return;
    }
    if (!(event->buttons() & Qt::LeftButton) || !isLeftButtonPhysicallyDown()) {
        endMove();
        event->accept();
        return;
    }
    updateMove(event->globalPosition());
    event->accept();
}

void NativeInlineDragArea::mouseReleaseEvent(QMouseEvent *event) {
    if (m_target) {
        finishMoveFromRelease(event);
        return;
    }
    if (event)
        event->ignore();
}

void NativeInlineDragArea::mouseUngrabEvent() {
    endMove(false);
}

#include "native_inline_drag_area.moc"
