"""
小红书图文卡片渲染（本地 Pillow，无需 Unsplash / 无需训练）
输出 3:4 竖图，可直接发小红书图文。
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Optional, Tuple
import logging

from PIL import Image, ImageDraw, ImageFont


# 小红书常用竖图比例
CARD_W, CARD_H = 1080, 1440

THEMES = {
    "干货知识": {
        "bg": (245, 248, 255),
        "accent": (23, 119, 255),
        "title": (15, 23, 42),
        "body": (51, 65, 85),
        "chip": (232, 241, 255),
        "footer": (100, 116, 139),
    },
    "情绪共鸣": {
        "bg": (255, 246, 248),
        "accent": (244, 63, 94),
        "title": (76, 29, 49),
        "body": (88, 28, 45),
        "chip": (255, 228, 230),
        "footer": (159, 88, 110),
    },
    "种草带货": {
        "bg": (240, 253, 244),
        "accent": (22, 163, 74),
        "title": (20, 83, 45),
        "body": (22, 101, 52),
        "chip": (220, 252, 231),
        "footer": (74, 122, 90),
    },
    "职场吐槽": {
        "bg": (255, 251, 235),
        "accent": (217, 119, 6),
        "title": (120, 53, 15),
        "body": (146, 64, 14),
        "chip": (254, 243, 199),
        "footer": (146, 104, 54),
    },
    "学习成长": {
        "bg": (238, 242, 255),
        "accent": (79, 70, 229),
        "title": (30, 27, 75),
        "body": (55, 48, 120),
        "chip": (224, 231, 255),
        "footer": (99, 102, 241),
    },
    "生活记录": {
        "bg": (255, 247, 237),
        "accent": (234, 88, 12),
        "title": (124, 45, 18),
        "body": (154, 52, 18),
        "chip": (255, 237, 213),
        "footer": (194, 120, 70),
    },
}


def _find_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts\msyhbd.ttc") if bold else Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\msyh.ttc"),
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\msyhl.ttc"),
    ]
    for path in candidates:
        if path.exists():
            try:
                return ImageFont.truetype(str(path), size=size, index=0)
            except Exception:
                continue
    return ImageFont.load_default()


def _wrap(text: str, font: ImageFont.ImageFont, max_width: int, draw: ImageDraw.ImageDraw) -> List[str]:
    text = re.sub(r"\s+", " ", (text or "").strip())
    if not text:
        return []
    lines: List[str] = []
    current = ""
    for ch in text:
        trial = current + ch
        bbox = draw.textbbox((0, 0), trial, font=font)
        if bbox[2] - bbox[0] <= max_width:
            current = trial
        else:
            if current:
                lines.append(current)
            current = ch
    if current:
        lines.append(current)
    return lines


def _split_points(body: str, max_points: int = 4) -> List[str]:
    """从正文拆出适合做图的要点"""
    clean = re.sub(r"#\S+", "", body or "")
    parts = re.split(r"\n+|。|！|？|；", clean)
    points = []
    for p in parts:
        p = p.strip(" \t-•*✨💡🔥✅😭💭❗️")
        p = re.sub(r"^(第[一二三四五六七八九十\d]+[、.．]?)", "", p).strip()
        if 8 <= len(p) <= 42:
            points.append(p)
        if len(points) >= max_points:
            break
    if not points:
        chunk = clean.replace("\n", "")[:80]
        if chunk:
            points = [chunk]
    return points[:max_points]


class XiaohongshuCardRenderer:
    """生成小红书图文配图"""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.logger = logger or logging.getLogger(__name__)

    def render_set(
        self,
        title: str,
        body: str,
        tags: List[str],
        category: str,
        output_dir: Path,
        prefix: str,
    ) -> List[str]:
        """
        生成一套图文卡片：封面 + 内容页 + 标签页

        Returns:
            本地图片路径列表
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        theme = THEMES.get(category) or THEMES["干货知识"]
        points = _split_points(body, max_points=4)
        paths: List[str] = []

        cover = self._render_cover(title, category, theme)
        cover_path = output_dir / f"{prefix}_cover.png"
        cover.save(cover_path, "PNG", optimize=True)
        paths.append(str(cover_path))

        # 每 2 个要点一页，更像小红书多图
        for i in range(0, len(points), 2):
            page_points = points[i:i + 2]
            page = self._render_content_page(
                title=title,
                points=page_points,
                page_no=i // 2 + 1,
                theme=theme,
            )
            page_path = output_dir / f"{prefix}_page{i // 2 + 1}.png"
            page.save(page_path, "PNG", optimize=True)
            paths.append(str(page_path))

        tag_page = self._render_tag_page(title, tags, theme)
        tag_path = output_dir / f"{prefix}_tags.png"
        tag_page.save(tag_path, "PNG", optimize=True)
        paths.append(str(tag_path))

        self.logger.info(f"已生成 {len(paths)} 张小红书配图")
        return paths

    def _render_cover(self, title: str, category: str, theme: dict) -> Image.Image:
        img = Image.new("RGB", (CARD_W, CARD_H), theme["bg"])
        draw = ImageDraw.Draw(img)

        # 顶部色带
        draw.rounded_rectangle((60, 60, CARD_W - 60, 220), radius=28, fill=theme["accent"])
        brand_font = _find_font(36, bold=True)
        draw.text((100, 110), "红笔 · 小红书图文", font=brand_font, fill=(255, 255, 255))
        draw.text((100, 160), category, font=_find_font(28), fill=(255, 255, 255))

        # 装饰圆
        draw.ellipse((780, 980, 1080, 1280), fill=theme["chip"])
        draw.ellipse((-80, 1100, 220, 1400), fill=theme["chip"])

        title_font = _find_font(72, bold=True)
        lines = _wrap(title, title_font, CARD_W - 160, draw)[:5]
        y = 360
        for line in lines:
            draw.text((80, y), line, font=title_font, fill=theme["title"])
            y += 92

        tip_font = _find_font(30)
        draw.text((80, 1280), "左右滑查看干货要点 →", font=tip_font, fill=theme["footer"])
        return img

    def _render_content_page(
        self,
        title: str,
        points: List[str],
        page_no: int,
        theme: dict,
    ) -> Image.Image:
        img = Image.new("RGB", (CARD_W, CARD_H), theme["bg"])
        draw = ImageDraw.Draw(img)

        draw.rounded_rectangle((60, 60, CARD_W - 60, 160), radius=24, fill=theme["chip"])
        head_font = _find_font(30, bold=True)
        short_title = title if len(title) <= 18 else title[:17] + "…"
        draw.text((90, 95), f"要点 {page_no} · {short_title}", font=head_font, fill=theme["accent"])

        point_font = _find_font(44, bold=True)
        body_font = _find_font(36)
        y = 240
        for idx, point in enumerate(points, 1):
            draw.rounded_rectangle((70, y, CARD_W - 70, y + 360), radius=28, fill=(255, 255, 255))
            draw.ellipse((100, y + 40, 170, y + 110), fill=theme["accent"])
            draw.text((122, y + 52), str(idx), font=_find_font(36, bold=True), fill=(255, 255, 255))

            wrapped = _wrap(point, body_font, CARD_W - 260, draw)[:5]
            ty = y + 50
            for line in wrapped:
                draw.text((200, ty), line, font=body_font, fill=theme["body"])
                ty += 52
            y += 400

        draw.text((80, 1340), "红笔 Hongbi", font=_find_font(26), fill=theme["footer"])
        return img

    def _render_tag_page(self, title: str, tags: List[str], theme: dict) -> Image.Image:
        img = Image.new("RGB", (CARD_W, CARD_H), theme["bg"])
        draw = ImageDraw.Draw(img)

        draw.text((80, 120), "收藏前先码住", font=_find_font(52, bold=True), fill=theme["title"])
        draw.text((80, 200), "这些标签更容易被搜到", font=_find_font(32), fill=theme["footer"])

        tags = tags[:10] or ["小红书笔记", "干货分享"]
        x, y = 80, 320
        tag_font = _find_font(34, bold=True)
        for tag in tags:
            label = tag if tag.startswith("#") else f"#{tag}"
            bbox = draw.textbbox((0, 0), label, font=tag_font)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            pad_x, pad_y = 28, 18
            if x + tw + pad_x * 2 > CARD_W - 80:
                x = 80
                y += th + pad_y * 2 + 24
            draw.rounded_rectangle(
                (x, y, x + tw + pad_x * 2, y + th + pad_y * 2),
                radius=999,
                fill=theme["chip"],
            )
            draw.text((x + pad_x, y + pad_y), label, font=tag_font, fill=theme["accent"])
            x += tw + pad_x * 2 + 16

        draw.rounded_rectangle((80, 1100, CARD_W - 80, 1320), radius=28, fill=theme["accent"])
        draw.text((120, 1160), "觉得有用就互动一下", font=_find_font(40, bold=True), fill=(255, 255, 255))
        draw.text((120, 1230), "评论区聊聊你的真实感受～", font=_find_font(30), fill=(255, 255, 255))
        return img
