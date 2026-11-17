"""v2 原型：基于审查结论重新设计的关键页面

核心改动：
1. 备份完成页 → 清单离机（B1）：短文本/二维码 + 后果句式
2. 还原页 → 增量还原（差异对比）：当前机器 vs 清单
3. 失败分诊（S3）：按原因分组 + 每组一个按钮
4. 状态标记收敛为三态（S2）
5. 术语任务化（S4）
"""
from __future__ import annotations

from render import COLORS, Canvas, content_area, page_header, window


# ============ 1. 备份完成：清单离机（B1 修复） ============
def v2_01_saved():
    c = Canvas()
    window(c, "备份", "备份")
    x, cy, w, h = content_area(c)

    c.text(x + 32, cy + 24, "清单已保存", 24, True, COLORS["text"])
    c.text(x + 32, cy + 62, "52 个软件 · 2026-11-17 16:53", 13, False, COLORS["text_secondary"])

    # 后果句式警示（独占视觉重心）
    wy = cy + 96
    c.rect(x + 32, wy, w - 64, 96, fill=COLORS["danger_soft"], radius=8)
    c.rect(x + 32, wy, 4, 96, fill=COLORS["danger"], radius=2)
    c.icon(x + 60, wy + 30, "\uE7BA", 20, COLORS["danger"])
    c.text(x + 86, wy + 30, "重装系统会清空这台电脑", 16, True, COLORS["danger"], anchor="lm")
    c.text(x + 60, wy + 62, "请现在就把清单复制出去。否则重装后无法还原，需要重新一个个找。",
           13, False, COLORS["text"])

    # 三种离机方式（并列，主次分明）
    oy = wy + 116
    c.text(x + 32, oy, "选择一种方式带走", 13, True, COLORS["text_secondary"])

    cards = [
        ("\uE8C8", "发到微信", "复制成文本，发给自己", "复制清单文本", "primary"),
        ("\uE8B7", "存到 U 盘 / 网盘", "打开文件夹，手动复制", "打开所在文件夹", "secondary"),
        ("\uE8EF", "扫码保存", "手机扫一扫，存到相册", "显示二维码", "secondary"),
    ]
    cw = (w - 64 - 24) // 3
    cy0 = oy + 28
    for i, (icon, title, desc, btn, kind) in enumerate(cards):
        cx0 = x + 32 + i * (cw + 12)
        c.card(cx0, cy0, cw, 156)
        c.circle(cx0 + 32, cy0 + 36, 18, fill=COLORS["accent_soft"])
        c.icon(cx0 + 32, cy0 + 36, icon, 16, COLORS["accent"])
        c.text(cx0 + 60, cy0 + 28, title, 14, True, COLORS["text"])
        c.text(cx0 + 60, cy0 + 48, desc, 11, False, COLORS["text_tertiary"])
        c.button(cx0 + 20, cy0 + 100, cw - 40, 38, btn, kind, 12)

    # 底部：文件名提示
    fy = cy0 + 176
    c.rect(x + 32, fy, w - 64, 56, fill=COLORS["neutral_soft"], radius=8)
    c.icon(x + 56, fy + 28, "\uE8A5", 15, COLORS["text_secondary"])
    c.text(x + 78, fy + 20, "文件名已带日期和机器名，方便重装后认出来：", 11, False, COLORS["text_secondary"])
    c.text(x + 78, fy + 36, "软件清单_2026-11-17_我的台式机.json", 13, True, COLORS["text"])

    c.button(x + w - 232, fy + 76, 200, 42, "我知道了，准备重装", "secondary", 13)
    return c.save("v2-01-备份-清单离机.png")


# ============ 2. 还原：增量对比（核心新增） ============
def v2_02_diff():
    c = Canvas()
    window(c, "还原", "还原")
    x, cy, w, h = content_area(c)

    c.text(x + 32, cy + 24, "还原软件", 24, True, COLORS["text"])
    c.text(x + 32, cy + 62, "已对比当前电脑，看看还差哪些", 13, False, COLORS["text_secondary"])

    # 清单身份条（B3 修复）
    iy = cy + 92
    c.card(x + 32, iy, w - 64, 56)
    c.icon(x + 56, iy + 28, "\uE8A5", 15, COLORS["text_secondary"])
    c.text(x + 78, iy + 18, "软件清单_2026-11-17_我的台式机.json", 13, True, COLORS["text"])
    c.text(x + 78, iy + 38, "来自「我的台式机」· 备份于 2026-11-17 · 共 52 个软件", 11, False,
           COLORS["text_tertiary"])
    c.button(x + w - 120, iy + 12, 72, 32, "更换", "secondary", 12)

    # 差异对比（核心）
    dy = iy + 76
    c.text(x + 32, dy, "对比结果", 13, True, COLORS["text_secondary"])
    dy += 24

    # 三个数字卡
    nums = [("7", "还差这些", COLORS["warning"], COLORS["warning_soft"]),
            ("42", "已经装了", COLORS["success"], COLORS["success_soft"]),
            ("3", "应用商店", COLORS["text_secondary"], COLORS["neutral_soft"])]
    cw = (w - 64 - 24) // 3
    for i, (num, label, fg, bg) in enumerate(nums):
        cx0 = x + 32 + i * (cw + 12)
        c.card(cx0, dy, cw, 72)
        c.text(cx0 + 20, dy + 16, num, 26, True, fg)
        c.text(cx0 + 20 + c.text_w(num, 26, True) + 10, dy + 26, label, 12, False, COLORS["text_secondary"])
        if i == 0:
            c.text(cx0 + 20, dy + 50, "默认只下载这些", 11, False, COLORS["text_tertiary"])

    # 列表：只显示"还差的"
    ly = dy + 92
    c.text(x + 52, ly, "还差的 7 个软件", 12, True, COLORS["text_tertiary"])
    c.text(x + w - 200, ly, "下载来源", 12, True, COLORS["text_tertiary"])
    ly += 24

    items = [
        ("微信", "4.1.15.13", "官网", "ok", True),
        ("QQ", "9.9.36", "官网", "ok", True),
        ("Steam", "2.10.91", "官网", "ok", True),
        ("Notepad++", "8.9.8.1", "应用商店源", "ok", True),
        ("向日葵远程控制", "16.8.0", "无来源", "none", False),
        ("百度网盘", "8.7.4", "无来源", "none", False),
        ("迅雷", "25.1.13", "官网", "ok", True),
    ]
    list_h = 7 * 34 + 16
    c.card(x + 32, ly, w - 64, list_h)
    iy2 = ly + 8
    for name, ver, src, kind, checked in items:
        c.checkbox(x + 52, iy2 + 9, checked)
        c.text(x + 82, iy2 + 17, name, 13, False,
               COLORS["text"] if checked else COLORS["text_tertiary"], anchor="lm")
        c.text(x + w - 340, iy2 + 17, ver, 11, False, COLORS["text_tertiary"], anchor="lm")
        if src == "无来源":
            c.pill(x + w - 200, iy2 + 6, "需手动下载", COLORS["warning"], COLORS["warning_soft"])
        elif src == "官网":
            c.pill(x + w - 200, iy2 + 6, "官网", COLORS["success"], COLORS["success_soft"])
        else:
            c.pill(x + w - 200, iy2 + 6, "应用商店源", COLORS["accent"], COLORS["accent_soft"])
        iy2 += 34

    # 底部
    by = ly + list_h + 20
    c.text(x + 32, by + 6, "已装的 42 个不会重复下载。", 12, False, COLORS["text_secondary"])
    c.button(x + w - 200, by - 4, 168, 42, "下载 5 个", "primary", 14)
    return c.save("v2-02-还原-增量对比.png")


# ============ 3. 失败分诊（S3 修复） ============
def v2_03_failures():
    c = Canvas()
    window(c, "还原", "还原")
    x, cy, w, h = content_area(c)

    c.text(x + 32, cy + 24, "下载完成", 24, True, COLORS["text"])

    # 结论句先行
    c.icon(x + 36, cy + 66, "\uE73E", 18, COLORS["success"])
    c.text(x + 58, cy + 66, "42 个成功，5 个需要你手动处理", 15, True, COLORS["text"], anchor="lm")

    # 按原因分组
    gy = cy + 100
    groups = [
        ("链接失效", 2, "官网换了地址，工具找不到新的",
         "打开官网搜索", COLORS["danger"], COLORS["danger_soft"],
         [("微信", "https://weixin.qq.com"), ("百度网盘", "https://pan.baidu.com")]),
        ("需要登录", 1, "这类下载需要账号，工具不会绕过",
         "打开下载页", COLORS["warning"], COLORS["warning_soft"],
         [("向日葵远程控制", "https://sunlogin.oray.com")]),
        ("网络问题", 2, "网络不稳定，重试通常就能成功",
         "重试这 2 个", COLORS["accent"], COLORS["accent_soft"],
         [("迅雷", ""), ("网易云音乐", "")]),
    ]

    for title, count, desc, btn, fg, bg, items in groups:
        c.card(x + 32, gy, w - 64, 44 + len(items) * 28 + 16)
        c.rect(x + 32, gy, 4, 44 + len(items) * 28 + 16, fill=fg, radius=2)
        c.text(x + 52, gy + 16, f"{title}（{count} 个）", 14, True, fg)
        c.text(x + 52, gy + 36, desc, 11, False, COLORS["text_secondary"])
        c.button(x + w - 168, gy + 14, 136, 32, btn, "secondary", 12)

        iy = gy + 60
        for name, url in items:
            c.text(x + 60, iy, name, 12, False, COLORS["text"])
            if url:
                c.text(x + 180, iy, url, 11, False, COLORS["accent"])
            iy += 28
        gy += 44 + len(items) * 28 + 24

    # 底部
    c.button(x + w - 380, gy + 8, 168, 40, "复制失败清单", "secondary", 13)
    c.button(x + w - 200, gy + 8, 168, 40, "打开下载文件夹", "primary", 13)
    return c.save("v2-03-还原-失败分诊.png")


# ============ 4. 还原空状态（B2 + S1 修复） ============
def v2_04_restore_empty():
    c = Canvas()
    window(c, "还原", "还原")
    x, cy, w, h = content_area(c)
    cx = x + w // 2

    c.text(cx, cy + 60, "重装后：把安装包下载回来", 24, True, COLORS["text"], anchor="mm")
    c.text(cx, cy + 96, "选择重装前保存的清单文件", 13, False, COLORS["text_secondary"], anchor="mm")

    # 上次备份回显（S1 修复）
    ly = cy + 128
    c.rect(cx - 260, ly, 520, 64, fill=COLORS["accent_soft"], radius=8)
    c.icon(cx - 232, ly + 32, "\uE81C", 16, COLORS["accent"])
    c.text(cx - 208, ly + 20, "上次备份：2026-11-17 · 我的台式机 · 52 个软件", 12, True, COLORS["accent"])
    c.text(cx - 208, ly + 40, "如果文件还在，直接点这里打开", 11, False, COLORS["text_secondary"])
    c.button(cx + 120, ly + 16, 120, 32, "打开这份", "primary", 12)

    # 文件选择
    fy = ly + 88
    c.rect(cx - 260, fy, 520, 48, fill=COLORS["surface"], outline=COLORS["border_strong"], radius=6)
    c.icon(cx - 236, fy + 24, "\uE8A5", 15, COLORS["text_tertiary"])
    c.text(cx - 214, fy + 24, "选择其他清单文件…", 13, False, COLORS["text_tertiary"], anchor="lm")
    c.button(cx + 160, fy + 4, 100, 40, "浏览…", "secondary", 13)

    # 三问三答（B2 修复）
    qy = fy + 80
    c.text(cx, qy, "找不到这个文件？", 14, True, COLORS["text_secondary"], anchor="mm")

    qa = [
        ("这是什么文件", "重装前用这个工具保存的 .json 文件，记录了当时装了哪些软件"),
        ("我上次存到哪了", "常见位置：U 盘根目录、微信文件传输助手、网盘下载文件夹、桌面"),
        ("实在找不到", "可以在本机搜索「软件清单_*.json」，或重新扫描当前电脑"),
    ]
    yy = qy + 32
    for q, a in qa:
        c.text(cx - 260, yy, "· " + q, 12, True, COLORS["text"])
        c.text(cx - 260, yy + 18, "  " + a, 11, False, COLORS["text_tertiary"])
        yy += 44

    # 兜底入口
    c.button(cx - 100, yy + 16, 200, 40, "帮我在这台电脑上找找", "secondary", 12)
    return c.save("v2-04-还原-空状态.png")


if __name__ == "__main__":
    print("v2 prototypes:")
    v2_01_saved()
    v2_02_diff()
    v2_03_failures()
    v2_04_restore_empty()
