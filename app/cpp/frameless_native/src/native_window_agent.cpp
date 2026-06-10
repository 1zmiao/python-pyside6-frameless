#include "native_window_agent.h"

#include <QWKCore/windowagentbase.h>
#include <QWKQuick/quickwindowagent.h>

#include <QtCore/QCoreApplication>
#include <QtCore/QMargins>
#include <QtCore/QRectF>
#include <QtCore/QString>
#include <QtCore/QVariant>
#include <QtCore/QtGlobal>

#ifdef Q_OS_WIN
#    include <dwmapi.h>
#    include <windows.h>
#endif

#ifdef Q_OS_WIN
static void terminateCurrentProcess() {
    TerminateProcess(GetCurrentProcess(), 0);
}

static int nativeCornerRadiusPx(int radius, HWND hwnd) {
    if (radius <= 0)
        return 0;
    UINT dpi = 96;
    if (hwnd) {
        if (auto getDpiForWindow = reinterpret_cast<UINT(WINAPI *)(HWND)>(
                GetProcAddress(GetModuleHandleW(L"user32.dll"), "GetDpiForWindow"))) {
            dpi = getDpiForWindow(hwnd);
        }
    }
    const int scaledRadius = qMax(1, MulDiv(radius, int(dpi), 96));
    const int inwardBias = qBound(1, scaledRadius / 6, 3);
    return qMax(1, scaledRadius - inwardBias);
}
#endif

NativeWindowAgent::NativeWindowAgent(QObject *parent)
    : QWK::QuickWindowAgent(parent)
{
}

NativeWindowAgent::~NativeWindowAgent() {
    restoreClassBackgroundBrush();
    if (m_window)
        m_window->removeEventFilter(this);
    uninstallNativeShellFilter();
}

void NativeWindowAgent::setup(QQuickWindow *window) {
    if (!window)
        return;
    if (m_window && m_window != window)
        m_window->removeEventFilter(this);
    m_window = window;
    m_window->installEventFilter(this);
    QWK::QuickWindowAgent::setup(window);
    m_window->setColor(shellBackgroundColor());
    QWK::QuickWindowAgent::setWindowAttribute(QStringLiteral("no-system-menu"), true);
    setResizeHitTestInsets(4, 6);
    installNativeShellFilter();
    applyWindowAttributes();
}

void NativeWindowAgent::setTitleBar(QQuickItem *item) {
    if (item) {
        m_titleBarItem = item;
        QWK::QuickWindowAgent::setTitleBar(item);
    }
}

void NativeWindowAgent::setSystemButton(const QString &role, QQuickItem *item) {
    if (!item)
        return;
    const int button = systemButtonRole(role);
    if (button != QWK::WindowAgentBase::Unknown) {
        QWK::QuickWindowAgent::setSystemButton(
            static_cast<QWK::WindowAgentBase::SystemButton>(button), item);
        switch (button) {
        case QWK::WindowAgentBase::Minimize:
            m_minimizeButton = item;
            break;
        case QWK::WindowAgentBase::Maximize:
            m_maximizeButton = item;
            break;
        case QWK::WindowAgentBase::Close:
            m_closeButton = item;
            break;
        default:
            break;
        }
    }
}

void NativeWindowAgent::setHitTestVisible(QQuickItem *item, bool visible) {
    if (item)
        QWK::QuickWindowAgent::setHitTestVisible(item, visible);
}

void NativeWindowAgent::setCustomShadowEnabled(bool enabled) {
    m_customShadow = enabled;
    applyWindowAttributes();
}

void NativeWindowAgent::setCornerRadius(int radius) {
    m_cornerRadius = qBound(0, radius, 96);
    applyWindowAttributes();
}

void NativeWindowAgent::setShadowAsset(const QUrl &source, int margin, qreal opacity) {
    m_shadowSource = source;
    m_shadowMargin = qBound(0, margin, 128);
    m_shadowOpacity = qBound<qreal>(0.0, opacity, 1.0);
    Q_UNUSED(m_shadowSource)
    Q_UNUSED(m_shadowMargin)
    Q_UNUSED(m_shadowOpacity)
}

void NativeWindowAgent::setShellBackgroundColor(const QColor &color) {
    if (!color.isValid())
        return;
    const QColor nextColor = color.toRgb();
    if (m_shellBackgroundColor == nextColor)
        return;
    m_shellBackgroundColor = nextColor;
    if (m_window) {
        m_window->setColor(m_shellBackgroundColor);
#ifdef Q_OS_WIN
        HWND hwnd = reinterpret_cast<HWND>(m_window->winId());
        if (hwnd) {
            updateClassBackgroundBrush();
            InvalidateRect(hwnd, nullptr, FALSE);
        }
#endif
    }
}

void NativeWindowAgent::setResizeHitTestInsets(int edgeInset, int cornerInset) {
    const int edge = qBound(1, edgeInset, 64);
    const int corner = qBound(edge, cornerInset, 96);
    m_resizeEdgeInset = edge;
    m_resizeCornerInset = corner;
    setWindowAttribute(QStringLiteral("qrounded-resize-edge-inset"), edge);
    setWindowAttribute(QStringLiteral("qrounded-resize-corner-inset"), corner);
}

void NativeWindowAgent::setFastExitOnClose(bool enabled) {
    m_fastExitOnClose = enabled;
}

bool NativeWindowAgent::isMaximized(QQuickWindow *window) const {
    QQuickWindow *target = window ? window : m_window.data();
    if (!target)
        return false;
#ifdef Q_OS_WIN
    HWND hwnd = reinterpret_cast<HWND>(target->winId());
    if (hwnd)
        return IsZoomed(hwnd);
#endif
    return target->visibility() == QWindow::Maximized || target->visibility() == QWindow::FullScreen;
}

void NativeWindowAgent::toggleMaximized(QQuickWindow *window) {
    QQuickWindow *target = window ? window : m_window.data();
    if (!target)
        return;

#ifdef Q_OS_WIN
    HWND hwnd = reinterpret_cast<HWND>(target->winId());
    if (hwnd) {
        const WPARAM command = IsZoomed(hwnd) ? SC_RESTORE : SC_MAXIMIZE;
        SendMessageW(hwnd, WM_SYSCOMMAND, command, 0);
        return;
    }
#endif

    if (target->visibility() == QWindow::Maximized || target->visibility() == QWindow::FullScreen)
        target->showNormal();
    else
        target->showMaximized();
}

bool NativeWindowAgent::eventFilter(QObject *watched, QEvent *event) {
    if (watched == m_window.data() && event) {
        switch (event->type()) {
        case QEvent::Close:
            if (m_fastExitOnClose) {
#ifdef Q_OS_WIN
                terminateCurrentProcess();
#else
                QCoreApplication::exit(0);
#endif
                return true;
            }
            break;
        case QEvent::Show:
            applyWindowAttributes();
            break;
        case QEvent::WindowStateChange:
            applyWindowAttributes();
            break;
        case QEvent::Resize:
            applyWindowRegion(false);
            break;
        default:
            break;
        }
    }
    return QObject::eventFilter(watched, event);
}

bool NativeWindowAgent::nativeEventFilter(const QByteArray &eventType, void *message, qintptr *result) {
#ifdef Q_OS_WIN
    if (!m_window || !message)
        return false;
    if (eventType != QByteArrayLiteral("windows_generic_MSG")
        && eventType != QByteArrayLiteral("windows_dispatcher_MSG")) {
        return false;
    }

    MSG *msg = static_cast<MSG *>(message);
    HWND hwnd = reinterpret_cast<HWND>(m_window->winId());
    if (!hwnd || !msg->hwnd)
        return false;
    HWND targetRoot = GetAncestor(hwnd, GA_ROOT);
    HWND messageRoot = GetAncestor(msg->hwnd, GA_ROOT);
    if (msg->hwnd != hwnd && (!targetRoot || !messageRoot || targetRoot != messageRoot))
        return false;

    if (msg->message == WM_NCHITTEST) {
        const int hit = nativeSystemButtonHitTest(msg->lParam);
        if (hit != HTNOWHERE) {
            if (result)
                *result = hit;
            return true;
        }
    }

    switch (msg->message) {
    case WM_CLOSE:
        if (m_fastExitOnClose) {
            if (result)
                *result = 0;
            terminateCurrentProcess();
            return true;
        }
        return false;
    case WM_SYSCOMMAND:
        if (m_fastExitOnClose && ((msg->wParam & 0xFFF0) == SC_CLOSE)) {
            if (result)
                *result = 0;
            terminateCurrentProcess();
            return true;
        }
        return false;
    case WM_ERASEBKGND: {
        if (msg->hwnd != hwnd)
            return false;
        HDC hdc = reinterpret_cast<HDC>(msg->wParam);
        if (!hdc)
            return false;
        RECT rect = {};
        if (!GetClientRect(hwnd, &rect))
            return false;
        const QColor color = shellBackgroundColor();
        HBRUSH brush = CreateSolidBrush(RGB(color.red(), color.green(), color.blue()));
        if (!brush)
            return false;
        FillRect(hdc, &rect, brush);
        DeleteObject(brush);
        if (result)
            *result = 1;
        return true;
    }
    case WM_ENTERSIZEMOVE:
        return false;
    case WM_SIZING: {
        if (msg->lParam) {
            const RECT *rect = reinterpret_cast<const RECT *>(msg->lParam);
            const int targetWidth = rect->right - rect->left;
            const int targetHeight = rect->bottom - rect->top;
            if (m_customShadow)
                applyWindowRegionForNativeSize(targetWidth, targetHeight, false);
        }
        return false;
    }
    case WM_WINDOWPOSCHANGING: {
        WINDOWPOS *pos = reinterpret_cast<WINDOWPOS *>(msg->lParam);
        if (pos && !(pos->flags & SWP_NOSIZE) && pos->cx > 0 && pos->cy > 0) {
            if (m_customShadow)
                applyWindowRegionForNativeSize(pos->cx, pos->cy, false);
        }
        return false;
    }
    case WM_SIZE:
    case WM_WINDOWPOSCHANGED:
        return false;
    case WM_EXITSIZEMOVE:
        return false;
    default:
        break;
    }
#else
    Q_UNUSED(eventType)
    Q_UNUSED(message)
    Q_UNUSED(result)
#endif
    return false;
}

int NativeWindowAgent::systemButtonRole(const QString &role) {
    const QString key = role.trimmed().toLower();
    if (key == QStringLiteral("icon") || key == QStringLiteral("windowicon"))
        return QWK::WindowAgentBase::WindowIcon;
    if (key == QStringLiteral("help"))
        return QWK::WindowAgentBase::Help;
    if (key == QStringLiteral("minimize") || key == QStringLiteral("min"))
        return QWK::WindowAgentBase::Minimize;
    if (key == QStringLiteral("maximize") || key == QStringLiteral("max") || key == QStringLiteral("restore"))
        return QWK::WindowAgentBase::Maximize;
    if (key == QStringLiteral("close"))
        return QWK::WindowAgentBase::Close;
    return QWK::WindowAgentBase::Unknown;
}

QColor NativeWindowAgent::shellBackgroundColor() const {
    if (m_shellBackgroundColor.isValid())
        return m_shellBackgroundColor;
    return QColor(16, 18, 24);
}

void NativeWindowAgent::applyWindowAttributes() {
    if (!m_window)
        return;
    m_window->setColor(shellBackgroundColor());

#ifdef Q_OS_WIN
    HWND hwnd = reinterpret_cast<HWND>(m_window->winId());
    if (!hwnd)
        return;
    updateClassBackgroundBrush();
    if (!m_customShadow) {
        const DWORD renderingPolicy = 0; // DWMNCRP_USEWINDOWSTYLE
        DwmSetWindowAttribute(hwnd, 2, &renderingPolicy, sizeof(renderingPolicy));
        const DWORD cornerPref = 2; // DWMWCP_ROUND
        DwmSetWindowAttribute(hwnd, 33, &cornerPref, sizeof(cornerPref));
        const COLORREF borderNone = 0xFFFFFFFE;
        DwmSetWindowAttribute(hwnd, 34, &borderNone, sizeof(borderNone));
        clearWindowRegion();
        return;
    }
    // Keep DWM non-client rendering enabled. Disabling it lets Win10 draw
    // classic frame/caption pixels behind the transparent QML chrome, which can
    // leak around rounded corners during live resize after maximize/restore.
    const DWORD ncPolicy = 2; // DWMNCRP_ENABLED
    DwmSetWindowAttribute(hwnd, 2, &ncPolicy, sizeof(ncPolicy));

    const QMargins frameMargins(0, 0, 0, 0);
    setWindowAttribute(QStringLiteral("extra-margins"),
                       QVariant::fromValue(frameMargins));
    const MARGINS margins = {frameMargins.left(), frameMargins.right(),
                             frameMargins.top(), frameMargins.bottom()};
    DwmExtendFrameIntoClientArea(hwnd, &margins);

    const DWORD doNotRound = 1; // DWMWCP_DONOTROUND
    DwmSetWindowAttribute(hwnd, 33, &doNotRound, sizeof(doNotRound));
    const COLORREF borderNone = 0xFFFFFFFE;
    DwmSetWindowAttribute(hwnd, 34, &borderNone, sizeof(borderNone));
    DwmSetWindowAttribute(hwnd, 35, &borderNone, sizeof(borderNone));

    // Keep visual clipping in this integration layer. QWindowKit owns native
    // hit-testing and window behavior; this project owns the custom rounded shell.
    applyWindowRegion(false);
#else
    Q_UNUSED(m_customShadow)
#endif
}

void NativeWindowAgent::applyWindowRegion(bool redraw) {
#ifdef Q_OS_WIN
    if (!m_window)
        return;
    HWND hwnd = reinterpret_cast<HWND>(m_window->winId());
    if (!hwnd)
        return;

    if (!m_customShadow) {
        clearWindowRegion();
        return;
    }

    RECT windowRect = {};
    if (!GetWindowRect(hwnd, &windowRect))
        return;
    const int width = windowRect.right - windowRect.left;
    const int height = windowRect.bottom - windowRect.top;
    if (width <= 0 || height <= 0) {
        clearWindowRegion();
        return;
    }

    applyWindowRegionForNativeSize(width, height, redraw);
#else
    Q_UNUSED(redraw)
#endif
}

void NativeWindowAgent::applyWindowRegionForNativeSize(int width, int height, bool redraw) {
#ifdef Q_OS_WIN
    if (!m_window)
        return;
    HWND hwnd = reinterpret_cast<HWND>(m_window->winId());
    if (!hwnd)
        return;
    if (width <= 0 || height <= 0)
        return;

    const bool square = m_cornerRadius <= 0
                        || m_window->visibility() == QWindow::Maximized
                        || m_window->visibility() == QWindow::FullScreen
                        || IsZoomed(hwnd);
    const int radius = square ? 0 : nativeCornerRadiusPx(m_cornerRadius, hwnd);
    const QSize size(width, height);
    if (m_lastRegionSize == size && m_lastRegionRadius == radius)
        return;

    HRGN region = square
                      ? CreateRectRgn(0, 0, width + 1, height + 1)
                      : CreateRoundRectRgn(0, 0, width + 1, height + 1, radius * 2, radius * 2);
    if (!region)
        return;
    const BOOL redrawRegion = redraw ? TRUE : FALSE;
    if (SetWindowRgn(hwnd, region, redrawRegion)) {
        m_lastRegionSize = size;
        m_lastRegionRadius = radius;
        return;
    }
    DeleteObject(region);
#else
    Q_UNUSED(redraw)
#endif
}

void NativeWindowAgent::installNativeShellFilter() {
#ifdef Q_OS_WIN
    if (m_nativeShellFilterInstalled || !qApp)
        return;
    qApp->installNativeEventFilter(this);
    m_nativeShellFilterInstalled = true;
#endif
}

void NativeWindowAgent::uninstallNativeShellFilter() {
#ifdef Q_OS_WIN
    if (!m_nativeShellFilterInstalled || !qApp)
        return;
    qApp->removeNativeEventFilter(this);
    m_nativeShellFilterInstalled = false;
#endif
}

void NativeWindowAgent::updateClassBackgroundBrush() {
#ifdef Q_OS_WIN
    if (!m_window)
        return;
    HWND hwnd = reinterpret_cast<HWND>(m_window->winId());
    if (!hwnd)
        return;

    const QColor color = shellBackgroundColor();
    HBRUSH nextBrush = CreateSolidBrush(RGB(color.red(), color.green(), color.blue()));
    if (!nextBrush)
        return;

    const LONG_PTR previous = SetClassLongPtrW(hwnd, GCLP_HBRBACKGROUND, reinterpret_cast<LONG_PTR>(nextBrush));
    if (!m_previousClassBackgroundBrush && previous)
        m_previousClassBackgroundBrush = static_cast<quintptr>(previous);
    HBRUSH oldBrush = reinterpret_cast<HBRUSH>(m_backgroundBrush);
    m_backgroundBrush = reinterpret_cast<quintptr>(nextBrush);
    if (oldBrush)
        DeleteObject(oldBrush);
#endif
}

void NativeWindowAgent::restoreClassBackgroundBrush() {
#ifdef Q_OS_WIN
    if (m_window) {
        HWND hwnd = reinterpret_cast<HWND>(m_window->winId());
        if (hwnd && m_previousClassBackgroundBrush) {
            SetClassLongPtrW(hwnd, GCLP_HBRBACKGROUND,
                             static_cast<LONG_PTR>(m_previousClassBackgroundBrush));
        }
    }
    HBRUSH brush = reinterpret_cast<HBRUSH>(m_backgroundBrush);
    if (brush)
        DeleteObject(brush);
    m_backgroundBrush = 0;
    m_previousClassBackgroundBrush = 0;
#endif
}

int NativeWindowAgent::nativeSystemButtonHitTest(qintptr lParam) const {
#ifdef Q_OS_WIN
    if (m_window) {
        HWND hwnd = reinterpret_cast<HWND>(m_window->winId());
        RECT rect = {};
        if (hwnd && GetWindowRect(hwnd, &rect)) {
            const POINT cursor = {
                static_cast<LONG>(static_cast<short>(LOWORD(lParam))),
                static_cast<LONG>(static_cast<short>(HIWORD(lParam))),
            };
            const int cornerInset = qMax(1, m_resizeCornerInset);
            if (cursor.y >= rect.top && cursor.y <= rect.top + cornerInset &&
                cursor.x >= rect.right - cornerInset - 1 && cursor.x <= rect.right) {
                return HTNOWHERE;
            }
        }
    }
    if (nativeItemContainsScreenPoint(m_minimizeButton, lParam))
        return HTREDUCE;
    if (nativeItemContainsScreenPoint(m_maximizeButton, lParam))
        return HTZOOM;
    if (nativeItemContainsScreenPoint(m_closeButton, lParam))
        return HTCLOSE;
#else
    Q_UNUSED(lParam)
#endif
    return 0;
}

bool NativeWindowAgent::nativeItemContainsScreenPoint(QQuickItem *item, qintptr lParam) const {
#ifdef Q_OS_WIN
    if (!m_window || !item || !item->isVisible() || !item->isEnabled())
        return false;
    const QPointF topLeft = item->mapToScene(QPointF(0.0, 0.0));
    QRectF rect(topLeft, item->size());
    if (rect.isEmpty())
        return false;
    const qreal dpr = qMax<qreal>(1.0, m_window->devicePixelRatio());
    POINT local = {
        LONG(qRound(rect.left() * dpr)),
        LONG(qRound(rect.top() * dpr)),
    };
    HWND hwnd = reinterpret_cast<HWND>(m_window->winId());
    if (!hwnd)
        return false;
    if (!ClientToScreen(hwnd, &local))
        return false;
    RECT screenRect = {
        local.x,
        local.y,
        LONG(local.x + qRound(rect.width() * dpr)),
        LONG(local.y + qRound(rect.height() * dpr)),
    };
    const POINT cursor = {
        static_cast<LONG>(static_cast<short>(LOWORD(lParam))),
        static_cast<LONG>(static_cast<short>(HIWORD(lParam))),
    };
    return PtInRect(&screenRect, cursor);
#else
    Q_UNUSED(item)
    Q_UNUSED(lParam)
    return false;
#endif
}

void NativeWindowAgent::clearWindowRegion() {
#ifdef Q_OS_WIN
    if (!m_window)
        return;
    HWND hwnd = reinterpret_cast<HWND>(m_window->winId());
    if (hwnd)
        SetWindowRgn(hwnd, nullptr, TRUE);
    m_lastRegionSize = QSize();
    m_lastRegionRadius = -1;
#endif
}

#include "native_window_agent.moc"
