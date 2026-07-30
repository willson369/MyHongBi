"""
小红书网感评分（规则清单，无需训练模型）
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional


TEMPLATES_PATH = Path(__file__).resolve().parents[2] / "data" / "xhs_templates.json"


@dataclass
class ScoreBreakdown:
    title_hook: int = 0
    opening_hook: int = 0
    emoji_rhythm: int = 0
    personal_tone: int = 0
    interaction: int = 0
    length_ok: int = 0
    anti_ai: int = 0

    @property
    def total(self) -> int:
        return (
            self.title_hook
            + self.opening_hook
            + self.emoji_rhythm
            + self.personal_tone
            + self.interaction
            + self.length_ok
            + self.anti_ai
        )


@dataclass
class ScoreResult:
    score: int
    grade: str
    breakdown: Dict[str, int]
    tips: List[str]
    category: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def load_templates() -> Dict[str, Any]:
    if not TEMPLATES_PATH.exists():
        return {"categories": [], "anti_ai_phrases": [], "score_weights": {}}
    with open(TEMPLATES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def get_category(category_name: str) -> Optional[Dict[str, Any]]:
    data = load_templates()
    for item in data.get("categories", []):
        if item.get("name") == category_name or item.get("id") == category_name:
            return item
    return data.get("categories", [None])[0]


def _grade(score: int) -> str:
    if score >= 85:
        return "爆款潜质"
    if score >= 70:
        return "网感在线"
    if score >= 55:
        return "还差点意思"
    return "偏AI味"


class XiaohongshuScorer:
    """基于公开创作规律的启发式评分器"""

    def __init__(self, templates: Optional[Dict[str, Any]] = None):
        self.templates = templates or load_templates()
        self.anti_ai = self.templates.get("anti_ai_phrases", [])
        self.weights = self.templates.get(
            "score_weights",
            {
                "title_hook": 20,
                "opening_hook": 20,
                "emoji_rhythm": 10,
                "personal_tone": 15,
                "interaction": 15,
                "length_ok": 10,
                "anti_ai": 10,
            },
        )

    def score(
        self,
        title: str,
        body: str,
        category: str = "干货知识",
    ) -> ScoreResult:
        tips: List[str] = []
        b = ScoreBreakdown()
        w = self.weights
        cat = get_category(category) or {}
        extra_forbidden = cat.get("forbidden_extra", [])

        # 1) 标题钩子
        title = (title or "").strip()
        has_emoji = bool(re.search(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", title))
        has_number = bool(re.search(r"\d", title))
        hook_words = ["谁懂", "我发现", "试过", "亲测", "绝了", "原来", "真的", "居然"]
        has_hook_word = any(k in title for k in hook_words)
        title_len_ok = 6 <= len(re.sub(r"[\U0001F300-\U0001FAFF\u2600-\u27BF\s]", "", title)) <= 22

        title_pts = 0
        if has_emoji:
            title_pts += w["title_hook"] // 4
        if has_number or has_hook_word:
            title_pts += w["title_hook"] // 2
        if title_len_ok:
            title_pts += w["title_hook"] // 4
        b.title_hook = min(title_pts, w["title_hook"])
        if b.title_hook < w["title_hook"] * 0.7:
            tips.append("标题再加点数字/情绪词/emoji，控制在20字左右")

        # 2) 开头钩子（前80字）
        opening = body.strip()[:80]
        open_hooks = ["以前", "那天", "谁懂", "说实话", "我本来", "突然", "一直以为", "姐妹"]
        if any(k in opening for k in open_hooks) or bool(
            re.search(r"[\U0001F300-\U0001FAFF]", opening[:20])
        ):
            b.opening_hook = w["opening_hook"]
        else:
            b.opening_hook = w["opening_hook"] // 3
            tips.append("开头前两句要更快抓人：痛点、反转或具体场景")

        # 3) emoji 节奏
        emoji_count = len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", body))
        if 3 <= emoji_count <= 18:
            b.emoji_rhythm = w["emoji_rhythm"]
        elif emoji_count > 0:
            b.emoji_rhythm = w["emoji_rhythm"] // 2
            tips.append("emoji 建议每段一个，不要刷屏也不要全无")
        else:
            tips.append("正文几乎没有 emoji，小红书阅读节奏会偏干")

        # 4) 个人语气
        personal = ["我", "你", "姐妹", "宝子", "真的", "亲测", "试过"]
        hits = sum(body.count(p) for p in personal)
        if hits >= 8:
            b.personal_tone = w["personal_tone"]
        elif hits >= 3:
            b.personal_tone = w["personal_tone"] // 2
            tips.append("多一点「我/你/真的」等口语，减少说明书感")
        else:
            tips.append("缺少个人视角，读起来像通稿")

        # 5) 互动
        interact_keys = ["吗", "呢", "评论", "收藏", "你们", "扣1", "聊聊"]
        if any(k in body for k in interact_keys) or "？" in body or "?" in body:
            b.interaction = w["interaction"]
        else:
            tips.append("文末加一句互动提问，提升评论可能")

        # 6) 篇幅
        pure = re.sub(r"#\S+", "", body)
        pure = re.sub(r"\s+", "", pure)
        n = len(pure)
        if 450 <= n <= 900:
            b.length_ok = w["length_ok"]
        elif 300 <= n < 450 or 900 < n <= 1200:
            b.length_ok = w["length_ok"] // 2
            tips.append("正文尽量落在 600-800 字（含口语呼吸感）")
        else:
            tips.append("正文过短或过长，影响完读率")

        # 7) 去 AI 味
        bad = []
        for phrase in list(self.anti_ai) + list(extra_forbidden):
            if phrase and phrase in body:
                bad.append(phrase)
        if not bad:
            b.anti_ai = w["anti_ai"]
        elif len(bad) == 1:
            b.anti_ai = w["anti_ai"] // 2
            tips.append(f"检测到书面/AI高频词：{bad[0]}，建议改口语")
        else:
            tips.append(f"AI味偏重：{', '.join(bad[:4])}…请改写")

        total = b.total
        return ScoreResult(
            score=total,
            grade=_grade(total),
            breakdown=asdict(b),
            tips=tips[:5],
            category=cat.get("name", category),
        )

    def build_rewrite_hint(self, result: ScoreResult) -> str:
        if not result.tips:
            return "保持口语、真诚、短句。"
        return "；".join(result.tips)
