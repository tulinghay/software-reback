"""生成还原页原型：空状态 / 计划预览 / 下载确认 / 下载中 / 完成"""
from __future__ import annotations

from render import COLORS, Canvas, content_area, page_header, window

PLAN = [
    ("7-Zip", "26.06", "官网直链", "ok"),
    ("Google Chrome", "131.0.6778", "应用商店源", "ok"),
    ("微信", "3.9.12.17", "官网直链", "ok"),
    ("Notepad++ (64-bit x64)", "8.9.8.1", "应用商店源", "ok"),
    ("Microsoft Office 专业增强版 2019", "16.0.10416", "官网直链", "ok"),
    ("QQ", "9.9.16", "无可用来源", "none"),
    ("向日葵远程控制", "15.5.0", "无可用来源", "none"),
    ("Steam", "2.10.91.91", "应用商店源", "ok"),
    ("百度网盘", "7.42.0", "官网直链", "ok"),
    ("Visual C++ 2015-2022 Redistributable", "14.40.33810", "官网直链", "ok"),
]

SRC_STYLE = {
    "官网直链": (COLORS["success"], COLORS["success_soft"]),
    "应用商店源": (COLORS["accent"], COLORS["accent_soft"]),
    "无可用来源": (COLORS["text_tertiary"], COLORS["neutral_soft"]),
}


def src_pill(c, x, y, label):
    fg, bg = SRC_STYLE[label]
    tw = c.text_w(label, 12)
    c.rect(x, y, tw + 16, 22, fill=bg, radius=11)
    c.text(x + (tw + 16) / 2, y + 11, label, 12, False, fg, anchor="mm")


# ---------------- 1. 空状态 ----------------
def p05_empty():
    c = Canvas()
    window(c, "还原", "还原")
    x, cy, w, h = content_area(c)
    cx = x + w // 2

    c.circle(cx, cy + 180, 56, fill=COLORS["accent_soft"])
    c.icon(cx, cy + 180, "\uE8B7", 40, COLORS["accent"])

    c.text(cx, cy + 268, "选择重装前保存的软件清单", 26, True, COLORS["text"], anchor="mm")
    c.text(cx, cy + 306, "找到 software.json 文件，工具会按它把安装包取回来。", 14, False,
           COLORS["text_secondary"], anchor="mm")

    # 文件选择框
    bw = 520
    c.rect(cx - bw // 2, cy + 344, bw, 48, fill=COLORS["surface"],
           outline=COLORS["border_strong"], radius=6)
    c.icon(cx - bw // 2 + 24, cy + 368, "\uE8A5", 16, COLORS["text_tertiary"])
    c.text(cx - bw // 2 + 46, cy + 368, r"C:\Users\18270\Downloads\software.json", 13, False,
           COLORS["text_secondary"], anchor="lm")
    c.button(cx + bw // 2 - 100, cy + 404, 100, 40, "浏览…", "primary", 13)

    # 找不到提示
    hy = cy + 480
    c.text(cx, hy, "找不到这个文件？它可能在：", 13, True, COLORS["text_secondary"], anchor="mm")
    hints = ["U 盘根目录", "微信文件传输助手", "网盘下载文件夹"]
    tx = cx - 200
    for t in hints:
        c.circle(tx + 3, hy + 28, 2.5, fill=COLORS["text_tertiary"])
        c.text(tx + 12, hy + 28, t, 12, False, COLORS["text_tertiary"], anchor="lm")
        tx += c.text_w(t, 12) + 40
    return c.save("05-还原-空状态.png")


# ---------------- 2. 计划预览 ----------------
def p06_plan():
    c = Canvas()
    window(c, "还原", "还原")
    x, cy, w, h = content_area(c)
    y = page_header(c, "下载计划", "先看看会发生什么，确认后再开始")

    # 清单来源
    c.card(x + 32, y + 72, w - 64, 56)
    c.icon(x + 56, y + 100, "\uE8A5", 15, COLORS["text_secondary"])
    c.text(x + 78, y + 92, r"C:\Users\18270\Downloads\software.json", 13, False, COLORS["text"])
    c.text(x + 78, y + 112, "备份于 2026-11-17 · 共 55 个软件", 11, False, COLORS["text_tertiary"])
    c.button(x + w - 120, y + 84, 72, 32, "更换", "secondary", 12)

    # 汇总
    sy = y + 146
    stats = [("36", "可以下载", COLORS["success"]), ("16", "没有来源", COLORS["warning"]),
             ("3", "应用商店", COLORS["text_secondary"])]
    for i, (num, label, col) in enumerate(stats):
        sx = x + 32 + i * 150
        c.text(sx, sy, num, 22, True, col)
        c.text(sx + c.text_w(num, 22, True) + 8, sy + 6, label, 12, False, COLORS["text_secondary"])

    # 表格
    ty = sy + 44
    c.text(x + 52, ty, "软件", 12, True, COLORS["text_tertiary"])
    c.text(x + w - 220, ty, "下载来源", 12, True, COLORS["text_tertiary"])
    ty += 24
    list_h = 340
    c.card(x + 32, ty, w - 64, list_h)
    iy = ty + 8
    for idx, (name, ver, src, kind) in enumerate(PLAN):
        if iy + 32 > ty + list_h:
            break
        if idx % 2 == 1:
            c.rect(x + 33, iy, w - 66, 32, fill=COLORS["surface_alt"])
        checked = kind != "none"
        c.checkbox(x + 52, iy + 8, checked)
        c.text(x + 82, iy + 16, name, 13, False,
               COLORS["text"] if checked else COLORS["text_tertiary"], anchor="lm")
        c.text(x + w - 300, iy + 16, ver, 11, False, COLORS["text_tertiary"], anchor="lm")
        src_pill(c, x + w - 220, iy + 5, src)
        iy += 32

    # 底部
    by = ty + list_h + 16
    c.text(x + 32, by + 10, "保存到：", 12, False, COLORS["text_secondary"])
    c.text(x + 92, by + 10, r"C:\Users\18270\Downloads\软件还原", 12, False, COLORS["text"])
    c.button(x + w - 200, by - 2, 168, 40, "开始下载", "primary", 14)
    return c.save("06-还原-计划预览.png")


# ---------------- 3. 下载确认弹窗 ----------------
def p07_confirm():
    c = Canvas()
    window(c, "还原", "还原")
    x, cy, w, h = content_area(c)
    page_header(c, "下载计划", "先看看会发生什么，确认后再开始")

    # 背景内容（让弹窗有上下文）
    c.card(x + 32, cy + 96, w - 64, 56)
    c.text(x + 52, cy + 112, r"C:\Users\18270\Downloads\software.json", 13, False, COLORS["text"])
    c.text(x + 52, cy + 132, "备份于 2026-11-17 · 共 55 个软件", 11, False, COLORS["text_tertiary"])

    # 压暗背景
    from PIL import Image, ImageDraw
    dark = Image.new("RGB", (c.w, c.h), (0, 0, 0))
    c.img = Image.blend(c.img, dark, 0.28)
    c.d = ImageDraw.Draw(c.img)

    # 对话框
    dw, dh = 480, 340
    dx = (c.w - dw) // 2 + 40
    dy = (c.h - dh) // 2
    c.rect(dx + 4, dy + 8, dw, dh, fill="#000000", radius=12)
    c.card(dx, dy, dw, dh, radius=12)

    c.text(dx + 28, dy + 28, "即将下载 36 个安装包", 19, True, COLORS["text"])

    rows = [("从官网下载", "21 个"), ("从应用商店源下载", "15 个")]
    ry = dy + 76
    for label, val in rows:
        c.text(dx + 28, ry, label, 13, False, COLORS["text_secondary"])
        c.text(dx + dw - 28, ry, val, 13, True, COLORS["text"], anchor="ra")
        ry += 26

    c.line(dx + 28, ry + 8, dx + dw - 28, ry + 8, COLORS["border"])
    ry += 24
    c.text(dx + 28, ry, "预计下载量", 13, False, COLORS["text_secondary"])
    c.text(dx + dw - 28, ry, "约 3.2 GB", 13, True, COLORS["text"], anchor="ra")
    ry += 26
    c.text(dx + 28, ry, "保存到", 13, False, COLORS["text_secondary"])
    c.text(dx + dw - 28, ry, r"C:\...\软件还原", 12, False, COLORS["text"], anchor="ra")

    # 提示
    c.rect(dx + 28, ry + 26, dw - 56, 52, fill=COLORS["neutral_soft"], radius=6)
    c.text(dx + 44, ry + 38, "另外 16 个软件没有下载来源，将跳过。", 12, False, COLORS["text_secondary"])
    c.text(dx + 44, ry + 58, "下载完成后可以查看清单，手动下载。", 12, False, COLORS["text_secondary"])

    # 按钮
    c.button(dx + dw - 232, dy + dh - 60, 96, 38, "取消", "secondary", 13)
    c.button(dx + dw - 124, dy + dh - 60, 96, 38, "开始下载", "primary", 13)
    return c.save("07-还原-下载确认.png")


# ---------------- 4. 下载中 ----------------
def p08_downloading():
    c = Canvas()
    window(c, "还原", "还原")
    x, cy, w, h = content_area(c)
    y = page_header(c, "正在下载", "8 / 36 已完成")

    # 总进度
    c.progress(x + 32, y + 70, w - 64, 10, 0.22)
    gy = y + 92
    c.text(x + 32, gy, "总进度 22%", 12, False, COLORS["text_secondary"])
    c.text(x + w - 32, gy, "预计还需 4 分 12 秒", 12, False, COLORS["text_secondary"], anchor="ra")

    # 并发任务卡
    tasks = [
        ("微信", "WeChatSetup.exe", 0.78, "42.1 MB/s", "12 秒", "18.4 / 23.6 MB"),
        ("Google Chrome", "ChromeStandaloneSetup64.exe", 0.61, "38.5 MB/s", "18 秒", "61.2 / 100.3 MB"),
        ("7-Zip", "7z2612-x64.exe", 0.30, "12.0 MB/s", "45 秒", "5.1 / 17.0 MB"),
    ]
    ty = y + 128
    for name, fname, ratio, speed, eta, size in tasks:
        c.card(x + 32, ty, w - 64, 84)
        c.text(x + 52, ty + 18, name, 14, True, COLORS["text"])
        c.text(x + 52 + c.text_w(name, 14, True) + 12, ty + 21, fname, 11, False, COLORS["text_tertiary"])
        c.text(x + w - 52, ty + 20, f"{int(ratio*100)}%", 13, True, COLORS["accent"], anchor="ra")
        c.progress(x + 52, ty + 42, w - 104, 8, ratio)
        c.text(x + 52, ty + 58, size, 11, False, COLORS["text_tertiary"])
        c.text(x + w - 52, ty + 58, f"{speed} · 剩余 {eta}", 11, False, COLORS["text_tertiary"], anchor="ra")
        ty += 96

    # 已完成统计
    sy = ty + 8
    c.text(x + 32, sy, "已完成 8 · 失败 0 · 排队 25", 12, False, COLORS["text_secondary"])

    # 操作
    c.button(x + w - 232, sy - 8, 96, 36, "暂停", "secondary", 13)
    c.button(x + w - 124, sy - 8, 96, 36, "取消", "secondary", 13)
    return c.save("08-还原-下载中.png")


# ---------------- 5. 下载完成 ----------------
def p09_done():
    c = Canvas()
    window(c, "还原", "还原")
    x, cy, w, h = content_area(c)
    y = page_header(c, "下载完成")

    # 统计
    c.icon(x + 36, y + 62, "\uE73E", 20, COLORS["success"])
    c.text(x + 58, y + 62, "33 个安装包已下载", 16, True, COLORS["text"], anchor="lm")

    sy = y + 92
    stats = [("33", "成功", COLORS["success"]), ("3", "失败", COLORS["danger"]),
             ("16", "跳过", COLORS["text_secondary"])]
    for i, (num, label, col) in enumerate(stats):
        sx = x + 32 + i * 130
        c.text(sx, sy, num, 20, True, col)
        c.text(sx + c.text_w(num, 20, True) + 6, sy + 5, label, 12, False, COLORS["text_secondary"])

    # 失败列表
    fy = sy + 40
    c.card(x + 32, fy, w - 64, 148, outline=COLORS["danger_soft"])
    c.text(x + 52, fy + 16, "失败的 3 个", 13, True, COLORS["danger"])
    fails = [
        ("微信", "下载地址已失效", "请手动从官网下载", None),
        ("迅雷", "文件校验未通过，已删除", "请勿安装，手动下载", None),
        ("网易云音乐", "网络连接失败", "检查网络后重试", "重试"),
    ]
    iy = fy + 44
    for name, reason, action, btn in fails:
        c.text(x + 52, iy, name, 13, True, COLORS["text"])
        c.text(x + 180, iy, reason, 12, False, COLORS["danger"])
        c.text(x + 180, iy + 18, "→ " + action, 12, False, COLORS["text_secondary"])
        if btn:
            c.button(x + w - 136, iy - 2, 72, 28, btn, "secondary", 12)
        iy += 34

    # 接下来
    ny = fy + 164
    c.rect(x + 32, ny, w - 64, 132, fill=COLORS["accent_soft"], radius=8)
    c.icon(x + 60, ny + 26, "\uE946", 18, COLORS["accent"])
    c.text(x + 82, ny + 26, "接下来", 14, True, COLORS["accent"], anchor="lm")
    c.text(x + 60, ny + 54, "安装包已下载到：", 12, False, COLORS["text"])
    c.text(x + 60, ny + 74, r"C:\Users\18270\Downloads\软件还原", 12, True, COLORS["text"])
    c.text(x + 60, ny + 98, "双击这些文件即可安装。工具不会自动安装，由你决定装哪个。",
           12, False, COLORS["text_secondary"])

    # 底部按钮
    c.button(x + w - 380, ny + 156, 168, 40, "打开下载文件夹", "primary", 13)
    c.button(x + w - 200, ny + 156, 168, 40, "查看详细报告", "secondary", 13)
    return c.save("09-还原-下载完成.png")


if __name__ == "__main__":
    print("restore pages:")
    p05_empty()
    p06_plan()
    p07_confirm()
    p08_downloading()
    p09_done()
