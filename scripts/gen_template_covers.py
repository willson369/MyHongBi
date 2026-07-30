"""生成品类模板封面图（小红书风格卡片）"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "static" / "images" / "templates"
OUT.mkdir(parents=True, exist_ok=True)

FONT_REG = Path(r"C:\Windows\Fonts\msyh.ttc")
FONT_BD = Path(r"C:\Windows\Fonts\msyhbd.ttc")
if not FONT_BD.exists():
    FONT_BD = FONT_REG

# id -> 视觉设定
THEMES = [
    {
        "id": "knowledge",
        "name": "干货知识",
        "tag": "可执行 · 有干货",
        "sample": "试过这3招✨效率真的翻倍了",
        "colors": ((219, 234, 254), (23, 119, 255), (37, 99, 235)),
    },
    {
        "id": "emotion",
        "name": "情绪共鸣",
        "tag": "谁懂啊 · 轻陪伴",
        "sample": "谁懂啊😭原来不是我不努力",
        "colors": ((252, 231, 243), (251, 113, 133), (225, 29, 72)),
    },
    {
        "id": "seed",
        "name": "种草带货",
        "tag": "真实体验 · 克制安利",
        "sample": "用了两周💡我真的回不去了",
        "colors": ((220, 252, 231), (34, 197, 94), (22, 163, 74)),
    },
    {
        "id": "workplace",
        "name": "职场吐槽",
        "tag": "真实现场 · 树洞共鸣",
        "sample": "上班第302天🙂我又破防了",
        "colors": ((254, 243, 199), (245, 158, 11), (217, 119, 6)),
    },
    {
        "id": "study",
        "name": "学习成长",
        "tag": "打卡方法 · 互相监督",
        "sample": "坚持21天✅英语终于捡回来了",
        "colors": ((224, 231, 255), (99, 102, 241), (79, 70, 229)),
    },
    {
        "id": "life",
        "name": "生活记录",
        "tag": "小确幸 · 有画面",
        "sample": "周末这样过☀️心情真的回血了",
        "colors": ((255, 237, 213), (249, 115, 22), (234, 88, 12)),
    },
    {
        "id": "beauty",
        "name": "美妆护肤",
        "tag": "亲测 · 说清肤质",
        "sample": "烂脸两周后✨我只换了这一步",
        "colors": ((250, 232, 255), (217, 70, 239), (192, 38, 211)),
    },
    {
        "id": "fitness",
        "name": "健身减脂",
        "tag": "可执行 · 不极端",
        "sample": "30天掉了4斤🔥终于不讨厌运动",
        "colors": ((204, 251, 241), (20, 184, 166), (13, 148, 136)),
    },
    {
        "id": "food",
        "name": "美食探店",
        "tag": "有食欲 · 真实评价",
        "sample": "这家面馆绝了🍜排队也值得",
        "colors": ((254, 226, 226), (244, 63, 94), (225, 29, 72)),
    },
    {
        "id": "sidehustle",
        "name": "副业搞钱",
        "tag": "务实路径 · 不画饼",
        "sample": "下班后做副业💰一个月多了小几千",
        "colors": ((207, 250, 254), (6, 182, 212), (8, 145, 178)),
    },
]


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    path = str(FONT_BD if bold else FONT_REG)
    try:
        return ImageFont.truetype(path, size=size, index=0)
    except Exception:
        return ImageFont.load_default()


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def make_cover(theme: dict, w: int = 960, h: int = 540) -> Image.Image:
    soft, mid, deep = theme["colors"]
    img = Image.new("RGB", (w, h), soft)
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        # 斜向渐变
        for x in range(w):
            tx = (x / max(w - 1, 1) + t) / 2
            c1 = lerp(soft, mid, min(1.0, tx * 1.15))
            c2 = lerp(mid, deep, max(0.0, tx - 0.35) / 0.65)
            mix = t * 0.55 + (x / w) * 0.45
            px[x, y] = lerp(c1, c2, mix * 0.65)

    # 柔光圆
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.ellipse((-80, -60, 420, 380), fill=(*soft, 110))
    od.ellipse((w - 360, h - 320, w + 80, h + 60), fill=(*deep, 70))
    od.ellipse((w // 2 - 40, 40, w // 2 + 280, 340), fill=(255, 255, 255, 40))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(img)

    # 品牌角标
    draw.rounded_rectangle((36, 28, 150, 72), radius=18, fill=(255, 255, 255, 230))
    # rounded_rectangle fill with RGB on RGB image
    draw.rounded_rectangle((36, 28, 150, 72), radius=18, fill=(255, 255, 255))
    draw.text((54, 36), "红笔", font=font(26, True), fill=deep)

    # 主标题
    draw.text((48, 160), theme["name"], font=font(72, True), fill=(15, 23, 42))
    draw.text((50, 250), theme["tag"], font=font(28), fill=(51, 65, 85))

    # 右侧「小红书笔记」假预览卡
    card = Image.new("RGBA", (380, 340), (0, 0, 0, 0))
    cd = ImageDraw.Draw(card)
    cd.rounded_rectangle((0, 0, 379, 339), radius=28, fill=(255, 255, 255, 235))
    cd.rounded_rectangle((18, 18, 361, 150), radius=18, fill=(*mid, 55))
    # 假图区色块纹理
    for i in range(6):
        y0 = 30 + i * 18
        cd.line((34, y0, 340, y0), fill=(*deep, 35), width=2)
    cd.text((34, 170), "爆款标题示例", font=font(18), fill=(100, 116, 139))
    # 标题换行
    sample = theme["sample"]
    lines = []
    cur = ""
    for ch in sample:
        cur += ch
        if len(cur) >= 12:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    ty = 200
    for line in lines[:3]:
        cd.text((34, ty), line, font=font(26, True), fill=(15, 23, 42))
        ty += 36
    cd.text((34, 300), "#红笔模板  #可直接用", font=font(18), fill=deep)

    # 阴影
    shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sx, sy = 540, 100
    sd.rounded_rectangle((sx + 8, sy + 12, sx + 388, sy + 352), radius=30, fill=(15, 23, 42, 50))
    shadow = shadow.filter(ImageFilter.GaussianBlur(10))
    img = Image.alpha_composite(img.convert("RGBA"), shadow)
    img.paste(card, (sx, sy), card)

    # 底部条
    bar = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    bd.rectangle((0, h - 54, w, h), fill=(255, 255, 255, 70))
    bd.text((48, h - 40), "点选模板 · 按结构施工成笔记", font=font(20), fill=(30, 41, 59))
    img = Image.alpha_composite(img, bar)
    return img.convert("RGB")


def main():
    for theme in THEMES:
        img = make_cover(theme)
        path = OUT / f"{theme['id']}.jpg"
        img.save(path, quality=90, optimize=True)
        # 也存一份小图用于列表
        thumb = img.resize((480, 270), Image.Resampling.LANCZOS)
        thumb.save(OUT / f"{theme['id']}_thumb.jpg", quality=88, optimize=True)
        print("wrote", path.name)


if __name__ == "__main__":
    main()
