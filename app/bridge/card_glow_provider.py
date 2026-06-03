from __future__ import annotations

import math
from functools import lru_cache

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath
from PySide6.QtQuick import QQuickImageProvider


class CardGlowImageProvider(QQuickImageProvider):
    """Generate cached theme-colored accent images for QML cards and rails."""

    def __init__(self) -> None:
        super().__init__(QQuickImageProvider.Image)

    def requestImage(self, image_id: str, size: QSize, requested_size: QSize) -> QImage:  # noqa: N802 - Qt API
        parts = [part for part in image_id.split("/") if part]
        kind = parts[0] if parts else "card"
        mode = parts[1] if len(parts) > 1 else "light"
        color = parts[2] if len(parts) > 2 else "537FCD"
        radius = _safe_int(parts[3], 12) if len(parts) > 3 else 12
        width = requested_size.width() if requested_size is not None and requested_size.width() > 0 else 384
        height = requested_size.height() if requested_size is not None and requested_size.height() > 0 else 160
        if kind == "side":
            image = self._side(mode, color, max(1, width), max(1, height), max(0, radius))
        else:
            image = self._card(mode, color, max(1, width), max(1, height), max(0, radius))
        if size is not None:
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image

    @staticmethod
    @lru_cache(maxsize=10)
    def _card(mode: str, color: str, width: int, height: int, radius: int) -> QImage:
        qcolor = QColor("#" + color.lstrip("#"))
        if not qcolor.isValid():
            qcolor = QColor("#537FCD")
        width = max(1, min(1400, int(width)))
        height = max(1, min(700, int(height)))
        radius = max(0, min(80, int(radius)))

        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, True)

        glow = _tint_template(_glow_template(), qcolor, mode, rim=False)
        rim = _tint_template(_rim_template(), qcolor, mode, rim=True)

        glow_h = max(72, min(int(height * 0.70), 220))
        glow_rect = QRectF(0, height - glow_h, width, glow_h)
        painter.setOpacity(0.84 if mode == "light" else 0.52)
        painter.drawImage(glow_rect, glow)

        top_glow_w = width
        top_glow_h = max(72, min(int(height * 0.52), 210))
        top_glow_rect = QRectF(0, 0, top_glow_w, top_glow_h)
        painter.setOpacity(0.56 if mode == "light" else 0.38)
        painter.drawImage(top_glow_rect, glow.mirrored(True, True))

        rim_h = max(5, min(12, int(height * 0.045)))
        rim_left = max(10, radius + 5)
        rim_right = max(28, radius + 24)
        rim_rect = QRectF(rim_left, height - rim_h, max(1, width - rim_left - rim_right), rim_h)
        painter.setOpacity(1.0 if mode == "light" else 0.90)
        painter.drawImage(rim_rect, rim)

        top_rim_w = max(96, min(int(width * 0.48), 360))
        top_rim_h = max(4, min(9, int(height * 0.035)))
        top_rim_x = max(radius + 8, width - top_rim_w - radius - 4)
        top_rim_rect = QRectF(top_rim_x, 0, top_rim_w, top_rim_h)
        painter.setOpacity(0.94 if mode == "light" else 0.78)
        painter.drawImage(top_rim_rect, rim.mirrored(True, True))

        painter.setOpacity(1.0)
        painter.setCompositionMode(QPainter.CompositionMode_DestinationIn)
        mask_image = QImage(width, height, QImage.Format_ARGB32)
        mask_image.fill(Qt.transparent)
        mask_painter = QPainter(mask_image)
        mask_painter.setRenderHint(QPainter.Antialiasing, True)
        mask = QPainterPath()
        mask.addRoundedRect(QRectF(0, 0, width, height), radius + 1, radius + 1)
        mask_painter.fillPath(mask, QColor(255, 255, 255, 255))
        mask_painter.end()
        painter.drawImage(0, 0, mask_image)
        painter.end()
        return image

    @staticmethod
    @lru_cache(maxsize=6)
    def _side(mode: str, color: str, width: int, height: int, radius: int) -> QImage:
        qcolor = QColor("#" + color.lstrip("#"))
        if not qcolor.isValid():
            qcolor = QColor("#537FCD")
        width = max(1, min(96, int(width)))
        height = max(1, min(1400, int(height)))

        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        glow_color = _tint(qcolor, mode, rim=False)
        rim_color = _tint(qcolor, mode, rim=True)
        glow_strength = 82 if mode == "light" else 58
        rim_strength = 160 if mode == "light" else 122

        for y in range(height):
            yn = y / max(1, height - 1)
            center = math.exp(-(((yn - 0.50) / 0.38) ** 2))
            upper = math.exp(-(((yn - 0.18) / 0.30) ** 2)) * 0.24
            lower = math.exp(-(((yn - 0.84) / 0.34) ** 2)) * 0.30
            vertical = min(1.0, 0.16 + 0.78 * center + upper + lower)
            glow_width = 0.28 + 0.30 * vertical
            rim_width = 0.010 + 0.028 * (vertical ** 1.16)

            for x in range(width):
                distance = (width - 1 - x) / max(1, width - 1)
                broad = math.exp(-((distance / glow_width) ** 2))
                rim = math.exp(-((distance / rim_width) ** 2))
                glow_alpha = int(glow_strength * vertical * (broad ** 1.32))
                rim_alpha = int(rim_strength * (vertical ** 0.78) * (rim ** 0.92))
                if glow_alpha <= 0 and rim_alpha <= 0:
                    continue

                pixel = QColor(0, 0, 0, 0)
                if glow_alpha > 0:
                    glow_pixel = QColor(glow_color)
                    glow_pixel.setAlpha(min(255, glow_alpha))
                    pixel = glow_pixel
                if rim_alpha > 0:
                    rim_pixel = QColor(rim_color)
                    rim_pixel.setAlpha(min(255, rim_alpha))
                    pixel = _source_over(pixel, rim_pixel)
                image.setPixelColor(x, y, pixel)
        return image


def _safe_int(value: str, fallback: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return fallback


def _mix_channel(value: int, target: int, ratio: float) -> int:
    ratio = max(0.0, min(1.0, ratio))
    return int(value * (1.0 - ratio) + target * ratio)


def _source_over(bottom: QColor, top: QColor) -> QColor:
    top_alpha = top.alpha() / 255.0
    bottom_alpha = bottom.alpha() / 255.0
    out_alpha = top_alpha + bottom_alpha * (1.0 - top_alpha)
    if out_alpha <= 0.0:
        return QColor(0, 0, 0, 0)
    red = int((top.red() * top_alpha + bottom.red() * bottom_alpha * (1.0 - top_alpha)) / out_alpha)
    green = int((top.green() * top_alpha + bottom.green() * bottom_alpha * (1.0 - top_alpha)) / out_alpha)
    blue = int((top.blue() * top_alpha + bottom.blue() * bottom_alpha * (1.0 - top_alpha)) / out_alpha)
    return QColor(red, green, blue, int(out_alpha * 255))


def _tint(color: QColor, mode: str, rim: bool) -> QColor:
    if mode == "light":
        ratio = 0.94 if rim else 0.88
        return QColor(
            _mix_channel(color.red(), 255, ratio),
            _mix_channel(color.green(), 255, ratio),
            _mix_channel(color.blue(), 255, ratio),
            255,
        )
    ratio = 0.62 if rim else 0.30
    return QColor(
        _mix_channel(color.red(), 235, ratio),
        _mix_channel(color.green(), 242, ratio),
        _mix_channel(color.blue(), 255, ratio),
        255,
    )


def _tint_template(template: QImage, color: QColor, mode: str, rim: bool) -> QImage:
    image = template.copy()
    painter = QPainter(image)
    painter.setCompositionMode(QPainter.CompositionMode_SourceIn)
    painter.fillRect(image.rect(), _tint(color, mode, rim))
    painter.end()
    return image

@lru_cache(maxsize=1)
def _glow_template() -> QImage:
    width, height = 384, 144
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    for y in range(height):
        yn = (height - 1 - y) / (height - 1)
        for x in range(width):
            xn = x / (width - 1)
            lower_edge = math.exp(-((xn - 0.42) / 0.88) ** 2 - (yn / 0.075) ** 2)
            left_pool = math.exp(-((xn - 0.11) / 0.42) ** 2 - (yn / 0.54) ** 2)
            broad_wash = math.exp(-((xn - 0.32) / 0.74) ** 2 - (yn / 0.35) ** 2)
            value = 0.34 * lower_edge + 0.43 * left_pool + 0.38 * broad_wash
            alpha = int(118 * (min(1.0, value) ** 1.62) + 22 * lower_edge)
            if alpha > 0:
                image.setPixelColor(x, y, QColor(255, 255, 255, min(255, alpha)))
    return image


@lru_cache(maxsize=1)
def _rim_template() -> QImage:
    width, height = 384, 12
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    for y in range(height):
        yn = y / (height - 1)
        for x in range(width):
            xn = x / (width - 1)
            along = math.exp(-((xn - 0.30) / 0.24) ** 2)
            thickness = 0.014 + 0.034 * along
            cross = math.exp(-(abs(yn - 0.92) / thickness) ** 2)
            alpha = int(235 * (along ** 0.72) * cross)
            if alpha > 0:
                image.setPixelColor(x, y, QColor(255, 255, 255, min(255, alpha)))
    return image
