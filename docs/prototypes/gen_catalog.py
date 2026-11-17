"""生成目录页 + 异常态原型"""
from __future__ import annotations

from render import COLORS, Canvas, content_area, page_header, window


# ---------------- 1. 目录页 ----------------
def p10_catalog():
    c = Canvas()
    window(c, "目录", "目录")
    x, cy, w, h = content_area(c)
    y = page_header(c, "软件目录",
                    "目录记录了每个软件的官方下载地址。条目越全，还原时能自动下载的软件越多。")

    # 顶部信息条
    ty = y + 76
    c.card(x + 32, ty, w - 64, 64)
    c.icon(x + 56, ty + 32, "\uE8F1", 18, COLORS["accent"])
    c.text(x + 82, ty + 22, "内置目录", 13, True, COLORS["text"])
    c.text(x + 82, ty + 42, "120 条 · 更新于 2026-11-15", 11, False, COLORS["text_tertiary"])
    c.button(x + w - 168, ty + 16, 136, 32, "导入自定义目录", "secondary", 12)

    # 健康度
    hy = ty + 84
    c.card(x + 32, hy, w - 64, 96)
    c.text(x + 52, hy + 18, "目录健康度", 13, True, COLORS["text"])
    c.progress(x + 52, hy + 44, w - 300, 10, 0.93, COLORS["success"])
    c.text(x + 52, hy + 62, "可用 112 · 失效 8", 11, False, COLORS["text_tertiary"])
    c.text(x + w - 200, hy + 40, "93%", 24, True, COLORS["success"], anchor="ra")
    c.button(x + w - 168, hy + 52, 136, 32, "检测失效链接", "secondary", 12)

    # 搜索
    sy = hy + 116
    c.rect(x + 32, sy, w - 64, 40, fill=COLORS["surface"], outline=COLORS["border_strong"], radius=6)
    c.icon(x + 56, sy + 20, "\uE721", 15, COLORS["text_tertiary"])
    c.text(x + 78, sy + 20, "搜索软件名称…", 13, False, COLORS["text_tertiary"], anchor="lm")

    # 条目列表
    ly = sy + 56
    entries = [
        ("微信", "官网", "已验证", "可用", "2026-11-15", "ok"),
        ("Google Chrome", "应用商店源", "已验证", "可用", "2026-11-14", "ok"),
        ("QQ", "官网", "未校验", "可用", "2026-11-12", "warn"),
        ("百度网盘", "官网", "已验证", "已失效", "2026-11-10", "dead"),
        ("向日葵远程控制", "官网", "已验证", "可用", "2026-11-08", "ok"),
    ]
    for idx, (name, src, verify, health, date, kind) in enumerate(entries):
        ey = ly + idx * 62
        c.card(x + 32, ey, w - 64, 54)
        c.text(x + 52, ey + 12, name, 13, True, COLORS["text"])
        c.text(x + 52, ey + 32, f"{src} · 校验{verify} · 上次检测 {date}", 11, False, COLORS["text_tertiary"])
        if kind == "ok":
            c.pill(x + w - 120, ey + 16, "可用", COLORS["success"], COLORS["success_soft"])
        elif kind == "warn":
            c.pill(x + w - 120, ey + 16, "可用", COLORS["success"], COLORS["success_soft"])
        else:
            c.pill(x + w - 120, ey + 16, "已失效", COLORS["danger"], COLORS["danger_soft"])
        c.icon(x + w - 60, ey + 27, "\uE76C", 12, COLORS["text_tertiary"])
    return c.save("10-目录.png")


# ---------------- 2. 磁盘空间不足 ----------------
def p11_disk_low():
    c = Canvas()
    window(c, "还原", "还原")
    x, cy, w, h = content_area(c)
    page_header(c, "下载计划", "先看看会发生什么，确认后再开始")

    # 警告条
    wy = cy + 96
    c.rect(x + 32, wy, w - 64, 84, fill=COLORS["danger_soft"], radius=8)
    c.rect(x + 32, wy, 4, 84, fill=COLORS["danger"], radius=2)
    c.icon(x + 60, wy + 26, "\uE7BA", 18, COLORS["danger"])
    c.text(x + 82, wy + 26, "磁盘空间不足", 14, True, COLORS["danger"], anchor="lm")
    c.text(x + 60, wy + 50, "需要 3.2 GB，但 C 盘只剩 1.8 GB。请更换下载位置，或先清理磁盘。",
           12, False, COLORS["text"])
    c.button(x + w - 200, wy + 24, 168, 36, "更换下载位置", "secondary", 12)

    # 空间明细
    sy = wy + 104
    c.card(x + 32, sy, w - 64, 88)
    c.text(x + 52, sy + 16, "磁盘空间", 12, True, COLORS["text_tertiary"])
    rows = [("C: 盘", "剩余 1.8 GB", "不足", COLORS["danger"]),
            ("D: 盘", "剩余 120 GB", "充足", COLORS["success"])]
    ry = sy + 40
    for label, space, status, col in rows:
        c.text(x + 52, ry, label, 12, False, COLORS["text"])
        c.text(x + 160, ry, space, 12, False, COLORS["text_secondary"])
        c.text(x + 300, ry, status, 12, True, col)
        ry += 24

    # 禁用状态按钮
    by = sy + 110
    c.text(x + 32, by + 10, "保存到：C:\\Users\\18270\\Downloads\\软件还原", 12, False,
           COLORS["text_tertiary"])
    c.rect(x + w - 200, by - 2, 168, 40, fill="#E0E0E0", radius=6)
    c.text(x + w - 116, by + 18, "开始下载", 14, False, "#9E9E9E", anchor="mm")
    return c.save("11-异常-磁盘不足.png")


# ---------------- 3. 识别失败提示 ----------------
def p12_parse_error():
    c = Canvas()
    window(c, "备份", "备份")
    x, cy, w, h = content_area(c)
    y = page_header(c, "扫描完成", "共找到 53 个软件")

    # 警告条
    wy = y + 76
    c.rect(x + 32, wy, w - 64, 72, fill=COLORS["warning_soft"], radius=8)
    c.rect(x + 32, wy, 4, 72, fill=COLORS["warning"], radius=2)
    c.icon(x + 60, wy + 26, "\uE7BA", 18, COLORS["warning"])
    c.text(x + 82, wy + 26, "有 2 条软件信息没能识别", 14, True, COLORS["warning"], anchor="lm")
    c.text(x + 60, wy + 50, "这不影响其他软件。这 2 个软件不会出现在清单里。", 12, False, COLORS["text"])
    c.button(x + w - 300, wy + 20, 96, 32, "查看详情", "secondary", 12)
    c.button(x + w - 196, wy + 20, 96, 32, "继续保存", "primary", 12)

    # 统计
    sy = wy + 92
    stats = [("34", "可以自动下载", COLORS["success"]), ("16", "需要手动处理", COLORS["warning"]),
             ("3", "应用商店", COLORS["text_secondary"])]
    for i, (num, label, col) in enumerate(stats):
        sx = x + 32 + i * 200
        c.text(sx, sy, num, 20, True, col)
        c.text(sx + c.text_w(num, 20, True) + 8, sy + 5, label, 12, False, COLORS["text_secondary"])

    # 简表
    ly = sy + 40
    c.card(x + 32, ly, w - 64, 300)
    items = [("7-Zip", "26.06", "可以自动下载", "ok"),
             ("Google Chrome", "131.0.6778", "可以自动下载", "ok"),
             ("微信", "3.9.12.17", "可以自动下载", "ok"),
             ("Microsoft Office 专业增强版 2019", "16.0.10416", "需要手动处理", "warn"),
             ("QQ", "9.9.16", "需要手动处理", "warn"),
             ("Microsoft Edge", "131.0.2903", "应用商店", "store")]
    iy = ly + 12
    for name, ver, label, kind in items:
        c.checkbox(x + 52, iy + 6, kind != "store")
        c.text(x + 82, iy + 14, name, 13, False, COLORS["text"], anchor="lm")
        c.text(x + w - 300, iy + 14, ver, 11, False, COLORS["text_tertiary"], anchor="lm")
        fg = {"ok": COLORS["success"], "warn": COLORS["warning"], "store": COLORS["text_secondary"]}[kind]
        bg = {"ok": COLORS["success_soft"], "warn": COLORS["warning_soft"], "store": COLORS["neutral_soft"]}[kind]
        c.pill(x + w - 160, iy + 3, label, fg, bg)
        iy += 34
    return c.save("12-异常-识别失败.png")


# ---------------- 4. 首次启动引导 ----------------
def p13_onboarding():
    c = Canvas()
    window(c, "备份", "备份")
    x, cy, w, h = content_area(c)

    # 居中卡片
    cw, ch = 560, 500
    cx = x + (w - cw) // 2
    cyy = cy + (h - ch) // 2 - 10
    c.card(cx, cyy, cw, ch, radius=12)

    c.circle(cx + cw // 2, cyy + 70, 36, fill=COLORS["accent_soft"])
    c.icon(cx + cw // 2, cyy + 70, "\uE896", 28, COLORS["accent"])

    c.text(cx + cw // 2, cyy + 136, "欢迎使用软件还原助手", 20, True, COLORS["text"], anchor="mm")
    c.text(cx + cw // 2, cyy + 170, "重装系统前，它会帮你记下装了哪些软件；", 13, False,
           COLORS["text_secondary"], anchor="mm")
    c.text(cx + cw // 2, cyy + 192, "重装后，按这份记录把安装包批量取回来。", 13, False,
           COLORS["text_secondary"], anchor="mm")

    # 三步说明
    steps = [("1", "扫描本机软件", "读取已安装的软件清单"),
             ("2", "保存清单", "存到 U 盘或网盘带走"),
             ("3", "重装后还原", "按清单批量下载安装包")]
    sy = cyy + 232
    for i, (num, title, desc) in enumerate(steps):
        c.circle(cx + 60, sy + 16, 13, fill=COLORS["accent"])
        c.text(cx + 60, sy + 16, num, 12, True, "#FFFFFF", anchor="mm")
        c.text(cx + 84, sy + 8, title, 13, True, COLORS["text"])
        c.text(cx + 84, sy + 26, desc, 11, False, COLORS["text_tertiary"])
        sy += 54

    c.button(cx + cw // 2 - 90, cyy + ch - 68, 180, 42, "开始使用", "primary", 14)
    return c.save("13-首次启动.png")


if __name__ == "__main__":
    print("catalog & edge cases:")
    p10_catalog()
    p11_disk_low()
    p12_parse_error()
    p13_onboarding()
