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

    def clear_cache(self) -> None:
        self._card.cache_clear()
        self._side.cache_clear()
        _tinted_glow_template.cache_clear()
        _tinted_rim_template.cache_clear()
        _tinted_side_glow_template.cache_clear()
        _tinted_side_rim_template.cache_clear()

    def requestImage(self, image_id: str, size: QSize, requested_size: QSize) -> QImage:  # noqa: N802 - Qt API
        parts = [part for part in image_id.split("/") if part]
        kind = parts[0] if parts else "card"
        mode = parts[1] if len(parts) > 1 else "light"
        color = parts[2] if len(parts) > 2 else "537FCD"
        radius = _safe_int(parts[3], 12) if len(parts) > 3 else 12
        render_scale_x, render_scale_y = _safe_scale_pair(parts[5] if len(parts) > 5 else "1.0")
        width = requested_size.width() if requested_size is not None and requested_size.width() > 0 else 384
        height = requested_size.height() if requested_size is not None and requested_size.height() > 0 else 160
        if kind == "side":
            image = self._side(mode, color, max(1, width), max(1, height), max(0, radius), render_scale_x, render_scale_y)
        else:
            image = self._card(mode, color, max(1, width), max(1, height), max(0, radius), render_scale_x, render_scale_y)
        if size is not None:
            size.setWidth(image.width())
            size.setHeight(image.height())
        return image

    @staticmethod
    @lru_cache(maxsize=6)
    def _card(mode: str, color: str, width: int, height: int, radius: int, render_scale_x: float, render_scale_y: float) -> QImage:
        width = max(1, min(1400, int(width)))
        height = max(1, min(700, int(height)))
        radius = max(0, min(80, int(radius)))
        render_scale_x = _clamped_scale(render_scale_x)
        render_scale_y = _clamped_scale(render_scale_y)

        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, True)

        color_key = _normalize_hex(color)
        glow = _tinted_glow_template(mode, color_key)
        rim = _tinted_rim_template(mode, color_key)

        glow_h = max(_scaled_px(72, render_scale_y), min(int(height * 0.70), _scaled_px(220, render_scale_y)))
        glow_rect = QRectF(0, height - glow_h, width, glow_h)
        painter.setOpacity(1.0 if mode == "light" else 0.69)
        painter.drawImage(glow_rect, glow)

        top_glow_w = width
        top_glow_h = max(_scaled_px(72, render_scale_y), min(int(height * 0.52), _scaled_px(210, render_scale_y)))
        top_glow_rect = QRectF(0, 0, top_glow_w, top_glow_h)
        painter.setOpacity(0.75 if mode == "light" else 0.51)
        painter.drawImage(top_glow_rect, glow.mirrored(True, True))

        rim_h = max(_scaled_px(5, render_scale_y), min(_scaled_px(12, render_scale_y), int(height * 0.045)))
        rim_left = max(_scaled_px(10, render_scale_x), radius + _scaled_px(5, render_scale_x))
        rim_right = max(_scaled_px(28, render_scale_x), radius + _scaled_px(24, render_scale_x))
        rim_rect = QRectF(rim_left, height - rim_h, max(1, width - rim_left - rim_right), rim_h)
        painter.setOpacity(1.0 if mode == "light" else 1.0)
        painter.drawImage(rim_rect, rim)

        top_rim_w = max(_scaled_px(96, render_scale_x), min(int(width * 0.48), _scaled_px(360, render_scale_x)))
        top_rim_h = max(_scaled_px(4, render_scale_y), min(_scaled_px(9, render_scale_y), int(height * 0.035)))
        top_rim_x = max(radius + _scaled_px(8, render_scale_x), width - top_rim_w - radius - _scaled_px(4, render_scale_x))
        top_rim_rect = QRectF(top_rim_x, 0, top_rim_w, top_rim_h)
        painter.setOpacity(1.0 if mode == "light" else 1.0)
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
    @lru_cache(maxsize=4)
    def _side(mode: str, color: str, width: int, height: int, radius: int, render_scale_x: float, render_scale_y: float) -> QImage:
        width = max(1, min(96, int(width)))
        height = max(1, min(1400, int(height)))
        render_scale_x = _clamped_scale(render_scale_x)
        render_scale_y = _clamped_scale(render_scale_y)

        image = QImage(width, height, QImage.Format_ARGB32)
        image.fill(Qt.transparent)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, True)
        color_key = _normalize_hex(color)
        painter.setOpacity(_low_resolution_opacity_compensation(min(render_scale_x, render_scale_y)))
        painter.drawImage(0, 0, _tinted_side_glow_template(mode, color_key, width, height))
        painter.drawImage(0, 0, _tinted_side_rim_template(mode, color_key, width, height))
        painter.end()
        return image


def _safe_int(value: str, fallback: int) -> int:
    try:
        return int(float(value))
    except Exception:
        return fallback


def _safe_float(value: str, fallback: float) -> float:
    try:
        return float(value)
    except Exception:
        return fallback


def _safe_scale_pair(value: str) -> tuple[float, float]:
    text = str(value or "1.0")
    if "x" in text:
        left, right = text.split("x", 1)
        return _safe_float(left, 1.0), _safe_float(right, 1.0)
    scale = _safe_float(text, 1.0)
    return scale, scale


def _clamped_scale(value: float) -> float:
    return max(0.25, min(1.0, float(value)))


def _scaled_px(value: int, scale: float) -> int:
    return max(1, int(round(value * _clamped_scale(scale))))


def _low_resolution_opacity_compensation(scale: float) -> float:
    # 低分辨率图被拉伸后，细高光会因为采样点变少略微变淡；只补偿采样损失，
    # 不改变主题本身的高光强度。
    return min(1.10, 1.0 + (1.0 - _clamped_scale(scale)) * 0.14)


def _normalize_hex(color: str) -> str:
    qcolor = QColor("#" + str(color).lstrip("#"))
    if not qcolor.isValid():
        qcolor = QColor("#537FCD")
    return qcolor.name(QColor.NameFormat.HexRgb).upper().lstrip("#")


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


@lru_cache(maxsize=8)
def _tinted_glow_template(mode: str, color: str) -> QImage:
    return _tint_template(_glow_template(), QColor("#" + color), mode, rim=False)


@lru_cache(maxsize=8)
def _tinted_rim_template(mode: str, color: str) -> QImage:
    return _tint_template(_rim_template(), QColor("#" + color), mode, rim=True)


@lru_cache(maxsize=4)
def _tinted_side_glow_template(mode: str, color: str, width: int, height: int) -> QImage:
    return _tint_template(_side_glow_template(width, height, mode), QColor("#" + color), mode, rim=False)


@lru_cache(maxsize=4)
def _tinted_side_rim_template(mode: str, color: str, width: int, height: int) -> QImage:
    return _tint_template(_side_rim_template(width, height, mode), QColor("#" + color), mode, rim=True)

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


@lru_cache(maxsize=8)
def _side_glow_template(width: int, height: int, mode: str) -> QImage:
    width = max(1, min(96, int(width)))
    height = max(1, min(1400, int(height)))
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    strength = 82 if mode == "light" else 58

    for y in range(height):
        yn = y / max(1, height - 1)
        center = math.exp(-(((yn - 0.50) / 0.38) ** 2))
        upper = math.exp(-(((yn - 0.18) / 0.30) ** 2)) * 0.24
        lower = math.exp(-(((yn - 0.84) / 0.34) ** 2)) * 0.30
        vertical = min(1.0, 0.16 + 0.78 * center + upper + lower)
        glow_width = 0.28 + 0.30 * vertical

        for x in range(width):
            distance = (width - 1 - x) / max(1, width - 1)
            broad = math.exp(-((distance / glow_width) ** 2))
            alpha = int(strength * vertical * (broad ** 1.32))
            if alpha > 0:
                image.setPixelColor(x, y, QColor(255, 255, 255, min(255, alpha)))
    return image


@lru_cache(maxsize=8)
def _side_rim_template(width: int, height: int, mode: str) -> QImage:
    width = max(1, min(96, int(width)))
    height = max(1, min(1400, int(height)))
    image = QImage(width, height, QImage.Format_ARGB32)
    image.fill(Qt.transparent)
    strength = 160 if mode == "light" else 122

    for y in range(height):
        yn = y / max(1, height - 1)
        center = math.exp(-(((yn - 0.50) / 0.38) ** 2))
        upper = math.exp(-(((yn - 0.18) / 0.30) ** 2)) * 0.24
        lower = math.exp(-(((yn - 0.84) / 0.34) ** 2)) * 0.30
        vertical = min(1.0, 0.16 + 0.78 * center + upper + lower)
        rim_width = 0.010 + 0.028 * (vertical ** 1.16)

        for x in range(width):
            distance = (width - 1 - x) / max(1, width - 1)
            rim = math.exp(-((distance / rim_width) ** 2))
            alpha = int(strength * (vertical ** 0.78) * (rim ** 0.92))
            if alpha > 0:
                image.setPixelColor(x, y, QColor(255, 255, 255, min(255, alpha)))
    return image
