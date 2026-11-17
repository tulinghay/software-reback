"""软件还原助手 · 高保真原型渲染器

用 Pillow 绘制桌面客户端界面原型，输出 PNG。
设计目标：Windows 11 Fluent 风格，浅色主题，中文界面。
"""
from __future__ import annotations

import pathlib
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

OUT = pathlib.Path(__file__).parent
FONT_DIR = pathlib.Path(r"C:\Windows\Fonts")

# ---------- 设计令牌 ----------
W, H = 1180, 780
TITLEBAR_H = 40
SIDEBAR_W = 200

COLORS = {
    "bg": "#F3F3F3",
    "surface": "#FFFFFF",
    "surface_alt": "#FAFAFA",
    "border": "#E5E5E5",
    "border_strong": "#D6D6D6",
    "text": "#1A1A1A",
    "text_secondary": "#616161",
    "text_tertiary": "#8A8A8A",
    "accent": "#0067C0",
    "accent_hover": "#1975C5",
    "accent_soft": "#E8F1FB",
    "success": "#0F7B0F",
    "success_soft": "#E7F4E7",
    "warning": "#9D5D00",
    "warning_soft": "#FFF4CE",
    "danger": "#C42B1C",
    "danger_soft": "#FDE7E9",
    "neutral_soft": "#F0F0F0",
    "track": "#E0E0E0",
}


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "msyhbd.ttc" if bold else "msyh.ttc"
    return ImageFont.truetype(str(FONT_DIR / name), size)


def icon_font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONT_DIR / "segmdl2.ttf"), size)


class Canvas:
    def __init__(self, w: int = W, h: int = H, bg: str = COLORS["bg"]):
        self.img = Image.new("RGB", (w, h), bg)
        self.d = ImageDraw.Draw(self.img)
        self.w, self.h = w, h

    # --- 基础图元 ---
    def rect(self, x, y, w, h, fill=None, outline=None, radius=0, width=1):
        if radius:
            self.d.rounded_rectangle([x, y, x + w - 1, y + h - 1], radius=radius,
                                     fill=fill, outline=outline, width=width)
        else:
            self.d.rectangle([x, y, x + w - 1, y + h - 1], fill=fill,
                             outline=outline, width=width)

    def text(self, x, y, s, size=14, bold=False, color=None, anchor="la"):
        color = color or COLORS["text"]
        self.d.text((x, y), s, font=font(size, bold), fill=color, anchor=anchor)

    def text_w(self, s, size=14, bold=False) -> int:
        return int(self.d.textlength(s, font=font(size, bold)))

    def icon(self, x, y, ch, size=16, color=None):
        self.d.text((x, y), ch, font=icon_font(size),
                    fill=color or COLORS["text_secondary"], anchor="mm")

    def circle(self, cx, cy, r, fill=None, outline=None, width=1):
        self.d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=fill,
                       outline=outline, width=width)

    def line(self, x1, y1, x2, y2, color=None, width=1):
        self.d.line([x1, y1, x2, y2], fill=color or COLORS["border"], width=width)

    # --- 复合组件 ---
    def button(self, x, y, w, h, label, kind="primary", size=14, icon=None):
        palette = {
            "primary": (COLORS["accent"], "#FFFFFF", None),
            "secondary": (COLORS["surface"], COLORS["text"], COLORS["border_strong"]),
            "ghost": (None, COLORS["accent"], None),
            "danger": (COLORS["danger"], "#FFFFFF", None),
        }
        fill, fg, outline = palette[kind]
        self.rect(x, y, w, h, fill=fill, outline=outline, radius=6)
        tw = self.text_w(label, size, bold=(kind == "primary"))
        if icon:
            iw = 16
            total = iw + 6 + tw
            sx = x + (w - total) / 2
            self.icon(sx + iw / 2, y + h / 2, icon, 15, fg)
            self.text(sx + iw + 6, y + h / 2, label, size, kind == "primary", fg, anchor="lm")
        else:
            self.text(x + w / 2, y + h / 2, label, size, kind == "primary", fg, anchor="mm")

    def progress(self, x, y, w, h, ratio, color=None, track=None):
        self.rect(x, y, w, h, fill=track or COLORS["track"], radius=h // 2)
        filled = max(h, int(w * ratio)) if ratio > 0 else 0
        if filled:
            self.rect(x, y, filled, h, fill=color or COLORS["accent"], radius=h // 2)

    def checkbox(self, x, y, checked=True, size=16, disabled=False):
        if checked:
            self.rect(x, y, size, size, fill=COLORS["accent"] if not disabled else "#BDBDBD", radius=4)
            self.icon(x + size / 2, y + size / 2, "\uE73E", 11, "#FFFFFF")
        else:
            self.rect(x, y, size, size, fill=COLORS["surface"],
                      outline=COLORS["text_tertiary"] if not disabled else "#CFCFCF", radius=4)

    def pill(self, x, y, label, fg, bg, size=12, padx=8, h=22):
        tw = self.text_w(label, size)
        w = tw + padx * 2
        self.rect(x, y, w, h, fill=bg, radius=h // 2)
        self.text(x + w / 2, y + h / 2, label, size, False, fg, anchor="mm")
        return w

    def card(self, x, y, w, h, fill=None, outline=None, radius=8):
        self.rect(x, y, w, h, fill=fill or COLORS["surface"],
                  outline=outline or COLORS["border"], radius=radius)

    def save(self, name: str):
        path = OUT / name
        self.img.save(path, "PNG")
        print(f"  saved: {path}")
        return path


# ---------- 窗口骨架 ----------
def window(c: Canvas, title: str, active_nav: str = "备份"):
    """绘制标题栏 + 侧边栏 + 内容区外框"""
    # 窗口圆角遮罩
    mask = Image.new("L", (c.w, c.h), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, c.w - 1, c.h - 1], radius=10, fill=255)
    bg = Image.new("RGB", (c.w, c.h), COLORS["bg"])
    c.img.paste(bg, (0, 0), mask)

    # 标题栏
    c.rect(0, 0, c.w, TITLEBAR_H, fill=COLORS["surface"])
    c.line(0, TITLEBAR_H - 1, c.w, TITLEBAR_H - 1, COLORS["border"])
    c.icon(20, TITLEBAR_H / 2, "\uE7B8", 15, COLORS["accent"])
    c.text(40, TITLEBAR_H / 2, "软件还原助手", 13, True, COLORS["text"], anchor="lm")

    # 窗口控制
    for i, ch in enumerate(["\uE921", "\uE922", "\uE8BB"]):
        cx = c.w - 30 - i * 46
        c.icon(cx, TITLEBAR_H / 2, ch, 12, COLORS["text_secondary"])

    # 侧边栏
    c.rect(0, TITLEBAR_H, SIDEBAR_W, c.h - TITLEBAR_H, fill=COLORS["surface_alt"])
    c.line(SIDEBAR_W - 1, TITLEBAR_H, SIDEBAR_W - 1, c.h, COLORS["border"])

    navs = [("备份", "\uE896", "备份软件清单"),
            ("还原", "\uE896", "还原软件"),
            ("目录", "\uE8F1", "软件目录")]
    y = TITLEBAR_H + 16
    for key, icon, label in navs:
        sel = key == active_nav
        if sel:
            c.rect(8, y, SIDEBAR_W - 16, 40, fill=COLORS["accent_soft"], radius=6)
            c.rect(8, y + 10, 3, 20, fill=COLORS["accent"], radius=2)
        color = COLORS["accent"] if sel else COLORS["text_secondary"]
        c.icon(32, y + 20, icon, 15, color)
        c.text(52, y + 20, label, 14, sel, COLORS["text"] if sel else COLORS["text_secondary"], anchor="lm")
        y += 44

    # 底部状态
    c.text(20, c.h - 30, "v0.2.0", 11, False, COLORS["text_tertiary"])


def content_area(c: Canvas) -> tuple[int, int, int, int]:
    """返回内容区 (x, y, w, h)"""
    x = SIDEBAR_W + 1
    y = TITLEBAR_H
    return x, y, c.w - x, c.h - y


def page_header(c: Canvas, title: str, subtitle: str = "", y=None):
    x, cy, w, h = content_area(c)
    y = y or cy + 24
    c.text(x + 32, y, title, 24, True, COLORS["text"])
    if subtitle:
        c.text(x + 32, y + 38, subtitle, 13, False, COLORS["text_secondary"])
    return y
