"""Render top-gainer table as a PNG (mobile-safe Excel-style grid)."""

from __future__ import annotations

import os
from io import BytesIO
from typing import Sequence

from PIL import Image, ImageDraw, ImageFont

GAINER_TABLE_HEADERS = ["Symbol", "Price", "% ↑", "Vol", "Float", "News"]
_RIGHT_ALIGN_COLS = frozenset({1, 2, 3, 4})

_BG = (47, 49, 54)
_HEADER_BG = (58, 61, 66)
_GRID = (88, 91, 96)
_TEXT = (220, 221, 222)
_MUTED = (185, 187, 190)
_STAR = (250, 166, 26)

_HEADER_TEXT = (114, 179, 255)  # light blue — stands out from row text

_CELL_PAD_X = 10
_ROW_H = 30
_HEADER_H = 34
_FONT_SIZE = 15
_HEADER_FONT_SIZE = 15
_FOOTER_PAD = 12
_FOOTER_LINE_H = 18
_FOOTER_FONT_SIZE = 13

_REGULAR_FONT_CANDIDATES = [
    os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "consola.ttf"),
    os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "cour.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
]
_BOLD_FONT_CANDIDATES = [
    os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "consolab.ttf"),
    os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "courbd.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/TTF/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono-Bold.ttf",
]


def _load_mono_font(size: int = _FONT_SIZE, *, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = _BOLD_FONT_CANDIDATES if bold else _REGULAR_FONT_CANDIDATES
    for path in candidates:
        if path and os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    for path in _REGULAR_FONT_CANDIDATES:
        if path and os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _text_width(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    if not text:
        return 0
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0]


def _column_widths(
    draw: ImageDraw.ImageDraw,
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    font,
    *,
    header_font=None,
) -> list[int]:
    header_font = header_font or font
    widths: list[int] = []
    for col_idx, header in enumerate(headers):
        max_w = _text_width(draw, header, header_font)
        for row in rows:
            if col_idx < len(row):
                max_w = max(max_w, _text_width(draw, row[col_idx], font))
        widths.append(max_w + _CELL_PAD_X * 2)
    return widths


def _footer_height(footer_lines: Sequence[str]) -> int:
    if not footer_lines:
        return 0
    return _FOOTER_PAD * 2 + len(footer_lines) * _FOOTER_LINE_H


def render_gainer_table_png(
    headers: Sequence[str],
    rows: Sequence[Sequence[str]],
    footer_lines: Sequence[str] | None = None,
) -> BytesIO:
    """Return PNG bytes in a seekable buffer."""
    if not rows:
        raise ValueError("Cannot render an empty gainer table")

    footer = list(footer_lines or [])
    font = _load_mono_font()
    header_font = _load_mono_font(_HEADER_FONT_SIZE, bold=True)
    footer_font = _load_mono_font(_FOOTER_FONT_SIZE)

    measure = Image.new("RGB", (1, 1), _BG)
    measure_draw = ImageDraw.Draw(measure)
    col_widths = _column_widths(measure_draw, headers, rows, font, header_font=header_font)

    width = sum(col_widths) + 1
    table_h = _HEADER_H + len(rows) * _ROW_H
    height = table_h + _footer_height(footer) + 1

    img = Image.new("RGB", (width, height), _BG)
    draw = ImageDraw.Draw(img)

    x = 0
    draw.rectangle([0, 0, width - 1, _HEADER_H], fill=_HEADER_BG)
    for col_idx, header in enumerate(headers):
        col_w = col_widths[col_idx]
        draw.line([(x, 0), (x, table_h - 1)], fill=_GRID, width=1)
        if col_idx in _RIGHT_ALIGN_COLS:
            tx = x + col_w - _CELL_PAD_X - _text_width(draw, header, header_font)
        else:
            tx = x + (col_w - _text_width(draw, header, header_font)) // 2
        ty = (_HEADER_H - _HEADER_FONT_SIZE) // 2
        draw.text((tx, ty), header, fill=_HEADER_TEXT, font=header_font)
        x += col_w
    draw.line([(width - 1, 0), (width - 1, table_h - 1)], fill=_GRID, width=1)
    draw.line([(0, _HEADER_H), (width - 1, _HEADER_H)], fill=_GRID, width=1)

    y = _HEADER_H
    for row in rows:
        x = 0
        draw.line([(0, y), (width - 1, y)], fill=_GRID, width=1)
        for col_idx, cell in enumerate(row):
            col_w = col_widths[col_idx]
            color = _STAR if col_idx == 0 and cell.strip().startswith("★") else _TEXT
            if col_idx in _RIGHT_ALIGN_COLS:
                tx = x + col_w - _CELL_PAD_X - _text_width(draw, cell, font)
            elif col_idx == len(headers) - 1:
                tx = x + (col_w - _text_width(draw, cell, font)) // 2
            else:
                tx = x + _CELL_PAD_X
            draw.text((tx, y + (_ROW_H - _FONT_SIZE) // 2), cell, fill=color, font=font)
            x += col_w
        y += _ROW_H

    draw.line([(0, table_h - 1), (width - 1, table_h - 1)], fill=_GRID, width=1)

    if footer:
        fy = table_h + _FOOTER_PAD
        for line in footer:
            if line:
                color = _TEXT if line.startswith("News Types Key:") else _MUTED
                draw.text((_CELL_PAD_X, fy), line, fill=color, font=footer_font)
            fy += _FOOTER_LINE_H

    draw.line([(0, height - 1), (width - 1, height - 1)], fill=_GRID, width=1)

    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return buf
