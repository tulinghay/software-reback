"""生成备份页原型：空状态 / 扫描中 / 扫描完成 / 保存成功"""
from __future__ import annotations

from render import (COLORS, Canvas, content_area, page_header, window)

SOFTWARE = [
    ("7-Zip", "26.06", "ok", "可以自动下载"),
    ("Google Chrome", "131.0.6778", "ok", "可以自动下载"),
    ("微信", "3.9.12.17", "ok", "可以自动下载"),
    ("Notepad++ (64-bit x64)", "8.9.8.1", "ok", "可以自动下载"),
    ("Microsoft Office 专业增强版 2019", "16.0.10416", "warn", "需要手动处理"),
    ("QQ", "9.9.16", "warn", "需要手动处理"),
    ("向日葵远程控制", "15.5.0", "warn", "需要手动处理"),
    ("Microsoft Edge", "131.0.2903", "store", "应用商店"),
    ("Windows Terminal", "1.21.2911", "store", "应用商店"),
    ("Visual C++ 2015-2022 Redistributable", "14.40.33810", "ok", "可以自动下载"),
    ("Steam", "2.10.91.91", "ok", "可以自动下载"),
    ("百度网盘", "7.42.0", "warn", "需要手动处理"),
]

STATUS_STYLE = {
    "ok": (COLORS["success"], COLORS["success_soft"], "\uE73E"),
    "warn": (COLORS["warning"], COLORS["warning_soft"], "\uE7BA"),
    "store": (COLORS["text_secondary"], COLORS["neutral_soft"], "\uE719"),
    "error": (COLORS["danger"], COLORS["danger_soft"], "\uE783"),
}


def status_pill(c, x, y, kind, label):
    fg, bg, ch = STATUS_STYLE[kind]
    tw = c.text_w(label, 12)
    w = tw + 34
    c.rect(x, y, w, 24, fill=bg, radius=12)
    c.icon(x + 14, y + 12, ch, 11, fg)
    c.text(x + 26, y + 12, label, 12, False, fg, anchor="lm")
    return w


# ---------------- 1. 空状态 ----------------
def p01_empty():
    c = Canvas()
    window(c, "备份", "备份")
    x, cy, w, h = content_area(c)
    cx = x + w // 2

    # 中央插画（简化：圆 + 图标）
    c.circle(cx, cy + 200, 56, fill=COLORS["accent_soft"])
    c.icon(cx, cy + 200, "\uE896", 40, COLORS["accent"])

    c.text(cx, cy + 290, "重装系统前，先备份软件清单", 26, True, COLORS["text"], anchor="mm")
    c.text(cx, cy + 330, "扫描这台电脑装了哪些软件，生成一份清单。", 14, False, COLORS["text_secondary"], anchor="mm")
    c.text(cx, cy + 354, "重装后可以用它把安装包批量取回来。", 14, False, COLORS["text_secondary"], anchor="mm")

    bw, bh = 220, 46
    c.button(cx - bw // 2, cy + 400, bw, bh, "开始扫描本机软件", "primary", 15)

    c.text(cx, cy + 470, "大约需要 1–2 分钟", 12, False, COLORS["text_tertiary"], anchor="mm")
    return c.save("01-备份-空状态.png")


# ---------------- 2. 扫描中 ----------------
def p02_scanning():
    c = Canvas()
    window(c, "备份", "备份")
    x, cy, w, h = content_area(c)
    y = page_header(c, "正在扫描本机软件")

    # 步骤指示
    steps = [("1", "读取已安装软件", True), ("2", "识别下载来源", False)]
    sx = x + 32
    for i, (num, label, done) in enumerate(steps):
        active = i == 0
        col = COLORS["accent"] if active else COLORS["text_tertiary"]
        c.circle(sx + 12, y + 92, 12, fill=col if active else COLORS["track"])
        c.text(sx + 12, y + 92, num, 12, True, "#FFFFFF" if active else COLORS["text_secondary"], anchor="mm")
        c.text(sx + 32, y + 92, label, 13, active, col if active else COLORS["text_tertiary"], anchor="lm")
        if i == 0:
            c.line(sx + 150, y + 92, sx + 190, y + 92, COLORS["border_strong"], 1)
        sx += 210

    # 进度条
    c.progress(x + 32, y + 126, w - 64, 8, 0.68)
    c.text(x + 32, y + 148, "68%", 13, True, COLORS["accent"])
    c.text(x + w - 32, y + 148, "已找到 38 个软件", 13, False, COLORS["text_secondary"], anchor="ra")

    # 实时列表
    ly = y + 186
    c.card(x + 32, ly, w - 64, 300)
    c.text(x + 52, ly + 20, "正在读取…", 12, False, COLORS["text_tertiary"])
    items = ["7-Zip", "Google Chrome", "微信", "Notepad++ (64-bit x64)",
             "Microsoft Office 专业增强版 2019", "QQ", "向日葵远程控制",
             "Microsoft Edge", "Windows Terminal", "Steam"]
    iy = ly + 46
    for name in items:
        c.icon(x + 56, iy + 8, "\uE73E", 11, COLORS["success"])
        c.text(x + 76, iy + 8, name, 13, False, COLORS["text"], anchor="lm")
        iy += 25
    # 渐隐
    c.rect(x + 33, ly + 246, w - 66, 53, fill=COLORS["surface"])

    c.button(x + 32, y + 502, 100, 36, "取消", "secondary")
    return c.save("02-备份-扫描中.png")


# ---------------- 3. 扫描完成 ----------------
def p03_done():
    c = Canvas()
    window(c, "备份", "备份")
    x, cy, w, h = content_area(c)
    y = page_header(c, "扫描完成", "共找到 55 个软件")

    # 三色汇总
    cy0 = y + 76
    cards = [
        ("36", "可以自动下载", COLORS["success"], COLORS["success_soft"], "\uE73E"),
        ("16", "需要手动处理", COLORS["warning"], COLORS["warning_soft"], "\uE7BA"),
        ("3", "应用商店", COLORS["text_secondary"], COLORS["neutral_soft"], "\uE719"),
    ]
    cw = (w - 64 - 24) // 3
    for i, (num, label, fg, bg, ch) in enumerate(cards):
        cx0 = x + 32 + i * (cw + 12)
        c.card(cx0, cy0, cw, 76)
        c.circle(cx0 + 32, cy0 + 38, 18, fill=bg)
        c.icon(cx0 + 32, cy0 + 38, ch, 16, fg)
        c.text(cx0 + 60, cy0 + 26, num, 22, True, COLORS["text"])
        c.text(cx0 + 60 + c.text_w(num, 22, True) + 8, cy0 + 32, label, 12, False, COLORS["text_secondary"])

    # 列表表头
    ly = cy0 + 96
    c.text(x + 52, ly + 6, "软件名称", 12, True, COLORS["text_tertiary"])
    c.text(x + w - 260, ly + 6, "版本", 12, True, COLORS["text_tertiary"])
    c.text(x + w - 150, ly + 6, "状态", 12, True, COLORS["text_tertiary"])

    # 列表
    ly += 28
    list_h = 330
    c.card(x + 32, ly, w - 64, list_h)
    iy = ly + 10
    for idx, (name, ver, kind, label) in enumerate(SOFTWARE):
        if iy + 34 > ly + list_h:
            break
        if idx % 2 == 1:
            c.rect(x + 33, iy, w - 66, 33, fill=COLORS["surface_alt"])
        checked = kind != "store"
        c.checkbox(x + 52, iy + 9, checked)
        c.text(x + 82, iy + 16, name, 13, False,
               COLORS["text"] if checked else COLORS["text_tertiary"], anchor="lm")
        c.text(x + w - 260, iy + 16, ver, 12, False, COLORS["text_secondary"], anchor="lm")
        status_pill(c, x + w - 150, iy + 5, kind, label)
        iy += 33

    # 底部操作
    by = ly + list_h + 14
    c.text(x + 32, by + 12, "取消勾选的软件不会被保存到清单", 12, False, COLORS["text_tertiary"])
    c.button(x + w - 200, by, 168, 40, "保存清单", "primary", 14)
    return c.save("03-备份-扫描完成.png")


# ---------------- 4. 保存成功 ----------------
def p04_saved():
    c = Canvas()
    window(c, "备份", "备份")
    x, cy, w, h = content_area(c)
    y = page_header(c, "清单已保存")

    # 成功提示
    c.icon(x + 36, y + 62, "\uE73E", 20, COLORS["success"])
    c.text(x + 58, y + 62, "已保存 52 个软件", 15, True, COLORS["success"], anchor="lm")

    # 路径卡片
    py = y + 96
    c.card(x + 32, py, w - 64, 92)
    c.text(x + 52, py + 20, "文件位置", 12, True, COLORS["text_tertiary"])
    c.text(x + 52, py + 44, r"C:\Users\18270\Documents\software.json", 14, False, COLORS["text"])
    c.button(x + w - 240, py + 52, 96, 32, "打开文件夹", "secondary", 12)
    c.button(x + w - 136, py + 52, 88, 32, "复制路径", "secondary", 12)

    # 备份提醒（重点）
    ry = py + 110
    c.rect(x + 32, ry, w - 64, 176, fill=COLORS["warning_soft"], radius=8)
    c.rect(x + 32, ry, 4, 176, fill=COLORS["warning"], radius=2)
    c.icon(x + 60, ry + 30, "\uE7BA", 18, COLORS["warning"])
    c.text(x + 82, ry + 30, "重装系统会清空这个文件", 15, True, COLORS["warning"], anchor="lm")
    c.text(x + 60, ry + 62, "请把它复制到 U 盘、网盘或手机：", 13, False, COLORS["text"])
    tips = ["微信文件传输助手", "百度网盘 / OneDrive", "U 盘"]
    tx = x + 60
    for t in tips:
        c.circle(tx + 3, ry + 92, 3, fill=COLORS["text_secondary"])
        c.text(tx + 14, ry + 92, t, 13, False, COLORS["text_secondary"], anchor="lm")
        tx += c.text_w(t, 13) + 44
    c.text(x + 60, ry + 128, "顺便把这个工具也复制一份，重装后才拿得回来。", 13, True, COLORS["warning"])

    # 主按钮
    c.button(x + w - 232, ry + 204, 200, 44, "我知道了，准备重装", "primary", 14)
    return c.save("04-备份-保存成功.png")


if __name__ == "__main__":
    print("backup pages:")
    p01_empty()
    p02_scanning()
    p03_done()
    p04_saved()
