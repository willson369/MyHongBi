"""
小红书笔记生成器（红笔增强：品类模板 + 网感打分 + 低分改写）
"""
import re
from typing import Optional, List, Tuple, Dict, Any
import logging

from ..ai_processor import AIProcessor
from ..xhs_scorer import XiaohongshuScorer, get_category, load_templates


class XiaohongshuGenerator:
    """小红书笔记生成器"""

    def __init__(
        self,
        ai_processor: AIProcessor,
        logger: Optional[logging.Logger] = None
    ):
        """
        初始化生成器

        Args:
            ai_processor: AI 处理器
            logger: 日志记录器
        """
        self.ai_processor = ai_processor
        self.logger = logger or logging.getLogger(__name__)
        self.scorer = XiaohongshuScorer()
        self.templates = load_templates()

    def generate(
        self,
        content: str,
        max_tokens: int = 2000,
        category: str = "干货知识",
        style_reference: str = "",
        score_threshold: int = 70,
    ) -> Tuple[str, List[str], List[str], Dict[str, Any]]:
        """
        生成小红书笔记：
        0) 提炼视频主旨（不是复述口播）
        1) 按品类爆款模板写标题
        2) 按爆款范文节奏写正文（纯文本，禁止 markdown）
        """
        cat = get_category(category) or {}
        cat_name = cat.get("name", category)

        # 第零步：提炼主旨（抗 ASR 噪声）
        self.logger.info(f"第零步：提炼视频主旨（品类={cat_name}）...")
        thesis = self._extract_thesis(content, cat)
        thesis_text = self._thesis_to_prompt_block(thesis)
        self.logger.info(f"主旨：{(thesis.get('gist') or '')[:80]}")

        # 第一步：生成5个标题（基于主旨，不基于垃圾口播）
        self.logger.info("第一步：生成小红书标题...")
        titles = self._generate_titles(thesis_text, cat, style_reference)

        if not titles:
            self.logger.warning("标题生成失败，使用品类爆款标题兜底")
            titles = []
            if cat.get("few_shot_title"):
                titles.append(cat["few_shot_title"])
            for v in cat.get("viral_examples") or []:
                if v.get("title") and v["title"] not in titles:
                    titles.append(v["title"])
            if not titles:
                titles = ["今天这件事我破防了"]

        main_title = self._strip_markdown(titles[0])
        titles = [self._strip_markdown(t) for t in titles]
        self.logger.info(f"已生成 {len(titles)} 个标题，主标题: {main_title[:30]}...")

        # 第二步：生成正文（主版本 + 备选）
        self.logger.info("第二步：按爆款模板写正文...")
        xiaohongshu_content = self._generate_content(
            thesis_text, main_title, max_tokens, cat, style_reference
        )
        xiaohongshu_content = self._strip_markdown(xiaohongshu_content or "")

        used_fallback = False
        if not xiaohongshu_content:
            self.logger.warning("正文生成失败，使用模板兜底成稿")
            xiaohongshu_content = self._fallback_note(thesis, main_title, cat)
            used_fallback = True

        if not xiaohongshu_content:
            empty_score = self.scorer.score(main_title, content, cat_name).to_dict()
            empty_score["thesis"] = thesis
            return content, titles, [], empty_score

        score_info = self.scorer.score(main_title, xiaohongshu_content, cat_name)
        self.logger.info(f"网感分：{score_info.score}（{score_info.grade}）")

        if (not used_fallback) and score_info.score < score_threshold:
            self.logger.info("网感分偏低，启动去AI味改写...")
            rewritten = self._rewrite_for_wanggan(
                xiaohongshu_content, main_title, cat, score_info
            )
            if rewritten:
                xiaohongshu_content = self._strip_markdown(rewritten)
                score_info = self.scorer.score(main_title, xiaohongshu_content, cat_name)
                self.logger.info(f"改写后网感分：{score_info.score}（{score_info.grade}）")

        alt_score = None
        if not used_fallback:
            alt_body = self._generate_content(
                thesis_text, main_title, max_tokens, cat, style_reference, variant=2
            )
            alt_body = self._strip_markdown(alt_body or "")
            if alt_body:
                alt_score = self.scorer.score(main_title, alt_body, cat_name)
                if alt_score.score > score_info.score:
                    self.logger.info("备选正文分数更高，采用备选版本")
                    xiaohongshu_content, score_info = alt_body, alt_score

        # 去掉正文里已有标签，单独提取
        xiaohongshu_content, tags = self._split_body_and_tags(xiaohongshu_content)
        if not tags:
            tags = self._extract_tags(xiaohongshu_content) or self._default_tags(cat_name)

        meta = score_info.to_dict()
        meta["titles"] = titles
        meta["alt_score"] = alt_score.to_dict() if alt_score else None
        meta["category"] = cat_name
        meta["thesis"] = thesis

        return xiaohongshu_content, titles, tags, meta

    def _extract_thesis(self, content: str, cat: Dict[str, Any]) -> Dict[str, Any]:
        """从口播/字幕提炼主旨，忽略 ASR 错字和废话。"""
        cat_name = cat.get("name", "干货知识")
        system_prompt = (
            "你是短视频内容编辑。任务是从嘈杂口播/字幕里提炼主旨。"
            "输入可能有语音识别错字，请靠上下文理解，不要复述错句。"
            "只输出 JSON，不要 markdown，不要解释。"
        )
        user_prompt = f"""品类：{cat_name}

原始口播/字幕（可能很吵、有错字）：
{content[:3500]}

请输出 JSON：
{{
  "gist": "一句话主旨（20字内）",
  "who": "叙事视角（如打工人/宝妈/学生）",
  "scene": "一个具体场景切片",
  "conflict": "核心矛盾或情绪点",
  "points": ["可写成笔记的3个要点", "要点2", "要点3"],
  "quote_worthy": "最值得放大的一句意思（不是原句照抄）",
  "avoid": "明确不要写进笔记的废话/错句"
}}"""
        raw = self.ai_processor.generate_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.3,
            max_tokens=700,
        ) or ""
        data = self._parse_json_loose(raw)
        if not data:
            data = self._heuristic_thesis(content, cat_name)
        return data

    def _heuristic_thesis(self, content: str, cat_name: str) -> Dict[str, Any]:
        """无 AI 时的主旨启发式提炼（去噪、抽短句）。"""
        text = re.sub(r"\s+", " ", content or "").strip()
        # 按句号/问号/感叹号切
        parts = [p.strip() for p in re.split(r"[。！？!?；;]", text) if p.strip()]
        # 过滤过短/明显噪声
        parts = [p for p in parts if 8 <= len(p) <= 60]
        keywords = ["不是", "最", "真的", "突然", "明白", "懂", "累", "破防", "发现", "换"]
        ranked = sorted(
            parts,
            key=lambda p: sum(1 for k in keywords if k in p) * 10 + min(len(p), 40),
            reverse=True,
        )
        top = ranked[:4] if ranked else ([text[:40]] if text else ["今天发生的一件事"])
        gist = top[0][:28]
        return {
            "gist": gist,
            "who": "打工人" if "职场" in cat_name else "当事人",
            "scene": top[0],
            "conflict": next((p for p in top if any(k in p for k in ["累", "不是", "破防", "消耗"])), top[0]),
            "points": top[:3],
            "quote_worthy": next((p for p in top if "不变" in p or "明白" in p or "发现" in p), top[-1]),
            "avoid": "语音识别错句、流水账时间线、无意义重复",
        }

    def _thesis_to_prompt_block(self, thesis: Dict[str, Any]) -> str:
        points = thesis.get("points") or []
        if isinstance(points, str):
            points = [points]
        points_txt = "\n".join(f"- {p}" for p in points[:5])
        return f"""【视频主旨】{thesis.get('gist', '')}
【视角】{thesis.get('who', '')}
【场景】{thesis.get('scene', '')}
【矛盾/情绪】{thesis.get('conflict', '')}
【可写要点】
{points_txt}
【最值得放大】{thesis.get('quote_worthy', '')}
【禁止写入】{thesis.get('avoid', 'ASR错字、流水账、无效时间线')}

重要：上面是提炼后的创作素材。请据此重写成小红书笔记，严禁复述原始口播错句。"""

    def _parse_json_loose(self, text: str) -> Dict[str, Any]:
        if not text:
            return {}
        text = text.strip()
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
        try:
            import json
            data = json.loads(text)
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
        m = re.search(r"\{[\s\S]*\}", text)
        if not m:
            return {}
        try:
            import json
            data = json.loads(m.group(0))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _strip_markdown(self, text: str) -> str:
        """小红书发布是纯文本：去掉 markdown 语法残留。"""
        if not text:
            return ""
        t = text.replace("\r\n", "\n")
        t = re.sub(r"^```[\s\S]*?```$", "", t, flags=re.M)
        t = re.sub(r"^#{1,6}\s+", "", t, flags=re.M)  # 仅去 markdown 标题，保留 #标签
        t = t.replace("**", "").replace("__", "").replace("~~", "")
        t = re.sub(r"`([^`]+)`", r"\1", t)
        t = re.sub(r"^\s*[-*•]\s+", "", t, flags=re.M)
        t = re.sub(r"^\s*\d+[.)、]\s+", "", t, flags=re.M)
        t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
        t = re.sub(r"\n{3,}", "\n\n", t)
        return t.strip()

    def _split_body_and_tags(self, text: str) -> Tuple[str, List[str]]:
        tags = re.findall(r"#([^\s#]+)", text or "")
        body = re.sub(r"(?:\s*#[^\s#]+)+\s*$", "", text or "").strip()
        body = re.sub(r"\n{0,2}(?:#[^\s#]+\s*)+$", "", body).strip()
        # 去重保序
        seen = set()
        clean_tags = []
        for t in tags:
            t = t.strip().lstrip("#")
            if t and t not in seen:
                seen.add(t)
                clean_tags.append(t)
        return body, clean_tags[:10]

    def _default_tags(self, cat_name: str) -> List[str]:
        mapping = {
            "职场吐槽": ["职场真实", "打工人日常", "程序员", "上班人", "树洞"],
            "干货知识": ["干货分享", "效率提升", "实用技巧", "自我管理", "收藏"],
            "情绪共鸣": ["情绪价值", "真实分享", "谁懂啊", "抱抱", "共鸣"],
            "种草带货": ["好物分享", "真实测评", "种草", "生活好物", "亲测"],
            "学习成长": ["学习方法", "自我提升", "打卡", "成长记录", "坚持"],
            "生活记录": ["生活碎片", "慢下来", "日常", "小确幸", "记录生活"],
            "美妆护肤": ["护肤分享", "真实测评", "敏感肌", "美妆", "变美日记"],
            "健身减脂": ["健身打卡", "减脂日记", "运动生活", "自律", "打卡"],
            "美食探店": ["美食探店", "本地好吃的", "吃货日记", "安利", "探店"],
            "副业搞钱": ["副业", "搞钱思维", "时间管理", "副业分享", "务实"],
        }
        return mapping.get(cat_name, ["小红书", "真实分享", "生活", "记录", "推荐"])

    def _fallback_note(
        self,
        thesis: Dict[str, Any],
        title: str,
        cat: Dict[str, Any],
    ) -> str:
        """AI 不可用时：用品类爆款范文骨架 + 主旨要点，拼出可发口语笔记。"""
        viral = (cat.get("viral_examples") or [{}])[0]
        base = (viral.get("body") or cat.get("few_shot_body") or "").strip()
        gist = (thesis.get("gist") or "").strip()
        scene = (thesis.get("scene") or gist).strip()
        conflict = (thesis.get("conflict") or "").strip()
        quote = (thesis.get("quote_worthy") or "").strip()
        points = thesis.get("points") or []
        if isinstance(points, str):
            points = [points]
        points = [str(p).strip() for p in points if str(p).strip()][:3]

        # 优先：改写范文骨架的前两段，再接入本视频要点
        paras = []
        if scene:
            paras.append(f"今天这件事真的把我按住了。{scene}。")
        if conflict and conflict != scene:
            paras.append(f"✨最耗人的不是加班本身，是{conflict}。")
        for i, p in enumerate(points):
            if p in (scene, conflict):
                continue
            emoji = ["💭", "🔥", "✅"][i % 3]
            paras.append(f"{emoji}{p}。")
        if quote and quote not in "".join(paras):
            paras.append(f"我想了很久才通：{quote}。")

        # 若太短，借范文后半段语气（去具体细节）
        if len("".join(paras)) < 80 and base:
            tail = base.split("\n\n")[-1]
            if "评论" in tail or "吗" in tail or "？" in tail:
                paras.append(tail)
            else:
                paras.append("你们有过同款瞬间吗？评论区树洞一下～")
        elif not any("？" in p or "吗" in p for p in paras):
            paras.append("你们今天也被消耗了吗？评论区树洞一下～")

        body = "\n\n".join(paras)
        body = re.sub(r"。{2,}", "。", body)
        tags = " ".join(f"#{t}" for t in self._default_tags(cat.get("name", "")))
        return f"{body}\n\n{tags}"

    def _generate_titles(
        self,
        content: str,
        cat: Optional[Dict[str, Any]] = None,
        style_reference: str = "",
    ) -> List[str]:
        """
        第一步：生成5个不同风格的标题

        Args:
            content: 输入内容

        Returns:
            标题列表
        """
        system_prompt = self._build_title_system_prompt()
        user_prompt = self._build_title_user_prompt(content, cat, style_reference)

        result = self.ai_processor.generate_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.8,  # 稍高温度增加创意
            max_tokens=500  # 标题不需要太多token
        )

        if not result:
            return []

        # 解析标题
        titles = []
        for line in result.split('\n'):
            line = line.strip()
            # 移除序号和标记
            line = re.sub(r'^\d+[.、)\]]\s*', '', line)
            line = re.sub(r'^\[?标题\d*\]?\s*', '', line, flags=re.IGNORECASE)
            line = re.sub(r'^[-*]\s*', '', line)

            if line and len(line) > 5 and len(line) < 50:
                titles.append(line)

        return titles[:5]  # 最多返回5个

    def _generate_content(
        self,
        content: str,
        title: str,
        max_tokens: int,
        cat: Optional[Dict[str, Any]] = None,
        style_reference: str = "",
        variant: int = 1,
    ) -> str:
        """
        第二步：根据选定的标题生成正文

        Args:
            content: 输入内容
            title: 选定的标题
            max_tokens: 最大token数

        Returns:
            正文内容
        """
        system_prompt = self._build_content_system_prompt()
        user_prompt = self._build_content_user_prompt(
            content, title, cat, style_reference, variant
        )

        result = self.ai_processor.generate_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.75 if variant == 1 else 0.9,
            max_tokens=max_tokens
        )

        return result if result else ""

    def _rewrite_for_wanggan(
        self,
        body: str,
        title: str,
        cat: Dict[str, Any],
        score_info,
    ) -> str:
        """低分正文的去AI味改写"""
        hint = self.scorer.build_rewrite_hint(score_info)
        forbidden = "、".join(
            (self.templates.get("anti_ai_phrases") or [])[:12]
            + (cat.get("forbidden_extra") or [])
        )
        system_prompt = (
            "你是小红书口语改写编辑。只输出改写后的正文纯文本。"
            "禁止 markdown（不要 # ** - 列表）。保留标签。"
        )
        user_prompt = f"""把下面这篇小红书正文改得更有网感、更像真人说话。

标题：{title}
品类：{cat.get('name', '')}
语气：{cat.get('tone', '真诚口语')}

必须改进：
{hint}

严禁出现：{forbidden}

原文：
{body}

要求：
1. 保留事实信息，不要编造视频里没有的内容
2. 短句、口语、每段可带1个emoji
3. 文末保留或补充互动句和#标签
4. 禁止任何 markdown 语法
5. 直接输出正文"""
        return self.ai_processor.generate_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.7,
            max_tokens=2000,
        ) or ""

    def _extract_tags(self, content: str) -> List[str]:
        """
        从生成的内容中提取标签

        Args:
            content: 生成的内容

        Returns:
            标签列表
        """
        tag_matches = re.findall(r'#([^\s#]+)', content)
        return tag_matches if tag_matches else []

    def _build_title_system_prompt(self) -> str:
        """构建标题生成的系统提示词"""
        return """你是小红书爆款标题写手。

规则：
1. 只输出 5 行标题，一行一个，不要序号，不要解释
2. 每个标题 ≤20 字，最多 2 个 emoji
3. 必须围绕「视频主旨」写，不要抄口播错句
4. 禁止 markdown（不要 # ** - 列表）
5. 禁止平台违规词：速来、必看、全网第一、免费送、血亏、封神等
6. 语气像真人发帖：谁懂啊 / 我发现 / 亲测 / 破防了 / 真的

风格轮换：数字悬念、情绪共鸣、反差对比、结果导向、对话互动"""

    def _build_title_user_prompt(
        self,
        content: str,
        cat: Optional[Dict[str, Any]] = None,
        style_reference: str = "",
    ) -> str:
        """构建标题生成的用户提示词"""
        cat = cat or {}
        styles = "、".join(cat.get("hook_styles") or ["数字悬念", "情感共鸣", "结果导向"])
        example = cat.get("few_shot_title") or "试过这3招✨效率真的翻倍了"
        viral = cat.get("viral_examples") or []
        viral_titles = "\n".join(
            f"- {v.get('title')}" for v in viral[:2] if v.get("title")
        )
        ref_block = ""
        if style_reference.strip():
            ref_block = f"\n用户爆款参考（模仿语气，勿照抄）：\n{style_reference.strip()[:400]}\n"

        return f"""请根据「视频主旨」生成 5 个不同风格的小红书标题。

品类：{cat.get('name', '干货知识')}
优先风格：{styles}
标题示例：{example}
品类爆款标题参考：
{viral_titles or example}
{ref_block}
{content}

直接输出 5 行标题："""

    def _build_content_system_prompt(self) -> str:
        """构建正文生成的系统提示词"""
        return """你是小红书爆款正文写手。

你的工作不是整理字幕，也不是写 Markdown 文档。
你要：先吃透「视频主旨」，再按爆款笔记节奏重写。

硬性输出格式（非常重要）：
1. 只输出可直接粘贴发小红书的纯文本
2. 禁止任何 markdown：不要 # 标题、不要 **加粗**、不要 -/* 列表、不要代码块
3. 用空行分段；段落开头可用 1 个 emoji
4. 文末单独一行写 5-8 个标签，形如 #职场真实 #打工人日常

写作要求：
1. 围绕主旨写，禁止复述语音识别错句和流水账时间线
2. 像朋友聊天：短句、口语、「我/你/真的」
3. 结构：钩子开场 → 2-4 个有画面的段落 → 一句清醒判断 → 互动提问
4. 正文 350-700 字（不含标签）
5. 禁止：首先/其次/最后/综上所述/赋能/闭环/抓手"""

    def _build_content_user_prompt(
        self,
        content: str,
        title: str,
        cat: Optional[Dict[str, Any]] = None,
        style_reference: str = "",
        variant: int = 1,
    ) -> str:
        """构建正文生成的用户提示词"""
        cat = cat or {}
        structure = " → ".join(cat.get("structure") or [
            "痛点开场", "方法展开", "个人体验", "互动结尾"
        ])
        details = cat.get("structure_detail") or []
        detail_txt = "\n".join(f"{i+1}. {d}" for i, d in enumerate(details[:4]))
        few_shot = cat.get("few_shot_body") or ""
        viral = cat.get("viral_examples") or []
        viral_block = ""
        if viral:
            v0 = viral[0]
            viral_block = f"爆款范文（学习节奏，勿照抄）：\n标题：{v0.get('title','')}\n{v0.get('body','')}\n"
        tone = cat.get("tone") or "真诚口语"
        forbidden = "、".join(
            (self.templates.get("anti_ai_phrases") or [])[:10]
            + (cat.get("forbidden_extra") or [])
        )
        ref_block = ""
        if style_reference.strip():
            ref_block = f"\n用户自己的爆款参考（学语气，不抄句子）：\n{style_reference.strip()[:600]}\n"
        variant_note = (
            "这是主版本：稳、真、抓人。"
            if variant == 1
            else "这是备选版本：开场角度和节奏必须与主版本明显不同。"
        )

        return f"""请根据标题和「视频主旨」写一篇小红书正文。

标题：
{title}

品类：{cat.get('name', '干货知识')}
语气：{tone}
结构骨架：{structure}
结构施工说明：
{detail_txt or '按品类骨架写，有画面，有互动'}
{variant_note}
{ref_block}
品类范文节奏：
{few_shot[:420]}

{viral_block}

创作素材（已提炼，请据此重写，不要复述原始口播）：
{content}

---
输出要求：
1. 不要输出标题本身
2. 不要 markdown
3. 文末输出标签行
4. 严禁这些词：{forbidden}
5. 让读者感觉「这是真人刚发的笔记」，不是整理稿

直接输出正文："""

    def _build_system_prompt(self) -> str:
        """构建系统提示词"""
        return """## 小红书爆款文案生成专家

### 角色设定
你是一名资深的小红书爆款文案写手。
你精通小红书平台的内容创作规则。
你擅长创作高互动、高转化的种草文案。

---

### 一、标题创作技能

你掌握以下5种标题创作方法：
1. **数字法则**：用具体数字增加可信度（如"7天"、"3个方法"）
2. **二极管标题**：制造强烈反差和对比效果
3. **疑问句式**：激发好奇心（如"为什么..."、"怎么..."）
4. **情绪共鸣**：使用高唤起情绪词，瞬间唤醒用户共鸣
5. **利益驱动**：直击痛点或利益点

【7大爆款标题风格】
- 数字悬念型：【3个懒人收纳法，房间一周不乱！】
- 情感共鸣型：【谁懂啊！这碗面直接治愈了我的周一！】
- 结果导向型：【跟着博主做，7天搞定Python基础！】
- 反差对比型：【从烂脸到水光肌，我只做了这两件事】
- 稀缺信息型：【这10个上海小众秘境，90%的人没去过】
- 对话互动型：【你的枕头选对了吗？快来对照这份指南！】
- 价值宣言型：【2025年投资自己，这3项技能最值钱】

---

### 二、小红书正文创作技能

#### 1. 写作风格
- **语言风格**：像朋友聊天，真诚、直接、有温度
- **句式结构**：简单明了，主谓宾清晰，一句话一个意思
- **词汇选择**：大白话优先，专业术语必须解释
- **段落节奏**：每段2-3句，保持呼吸感

#### 2. 写作开篇方法
- **金句开场**：用一句话抓住注意力
- **痛点切入**：直接说出用户困扰
- **反转开场**：先说常见误区，再给出正确方法
- **故事引入**：用个人经历引发共鸣

#### 3. 文本结构
- **开头**：emoji+金句/痛点（1-2句话）
- **主体**：分点叙述，每点前加emoji，3-5个要点
- **每个要点包含**：具体方法+个人体验+效果说明
- **结尾**：总结+互动引导

#### 4. 互动引导方法
- **提问式**："你们有遇到这种情况吗？"
- **征集式**："评论区说说你的方法～"
- **行动式**："赶紧收藏起来！"
- **共鸣式**："姐妹们懂我的扣1！"

#### 5. 小技巧
- 使用"姐妹们"、"宝子们"等亲昵称呼
- 适当使用网络流行语和梗
- 多用"你、我、他"，少用"其、该、此、彼"
- 多用"真的"、"绝了"、"爱了"等语气词
- 用"第一、第二、第三"而不是"首先、其次、最后"

#### 6. 爆炸词库
**情绪类**：绝了、爱了、yyds、无敌、炸裂、疯狂、上头、氛围感
**效果类**：秒杀、碾压、吊打、封神、神仙、手残党必备
**程度类**：超级、巨、狂、暴、极致
**共鸣类**：懂的都懂、破防了、DNA动了、真实、太真实了

#### 7. SEO标签规则
从生成的稿子中，抽取3-6个核心关键词。
生成#标签并放在文章最后。

#### 8. 口语化要求
文章的每句话都尽量口语化、简短。
避免长句和书面语。
一句话只表达一个完整意思。

#### 9. Emoji使用规则
在每段话的中间关键词处插入表情符号。
emoji优先用「✨/🔥/✅/💡/❗️/😭/🤔/💪」。

---

### 三、写作约束（严格执行）

**禁止使用以下内容**：
1. 不使用破折号（——）
2. 禁用"A而且B"的对仗结构
3. 不使用冒号（：），除非是对话或列表
4. 开头不用设问句
5. 一句话只表达一个完整意思
6. 每段不超过3句话
7. 避免嵌套从句和复合句
8. 多用"你、我、他"，少用"其、该、此、彼"

**平台禁忌词（严禁使用）**：
【诱导类】速来、必看、必收、千万不要、马上、抓紧、最后一波
【夸大类】全网第一、最全、最强、史上、终极、完美、天花板、封神
【营销类】免费送、0元购、薅羊毛、福利、红包、点击领取、价格感人
【负面类】丑哭、踩雷、血亏、别买、避坑、垃圾、后悔、翻车

**改写策略**：
1. **长句拆短**：把复合句拆成多个简单句
2. **术语翻译**：把专业词汇翻译成大白话
3. **增加温度**：适当加入个人感受和真实体验
4. **逻辑清晰**：用"第一、第二、第三"标注顺序

---

### 四、创作要求
1. 内容真诚可信，把"真诚"摆在第一位
2. 避免假大空，花里胡哨的内容
3. 避免使用广告法违禁词和平台敏感词
4. 保持小红书社区调性，注重用户体验
5. 每个标题和正文都要有独特视角
6. 正文控制在600-800字之间"""

    def _build_user_prompt(self, content: str) -> str:
        """构建用户提示词"""
        return f"""请将以下内容转换为爆款小红书笔记。

内容如下：
{content}

---

请严格按照以下格式输出内容。
只输出格式描述的部分。
不要解释创作过程。
不要添加任何提示词相关说明。

**输出格式**：

一. 标题
[标题1]
[标题2]
[标题3]
[标题4]
[标题5]

二. 正文
[正文内容]

标签：[#标签1 #标签2 #标签3 #标签4 #标签5]

---

**标题创作要求**：
1. 生成5个不同风格的标题，每个标题使用不同的爆款标题风格
2. 严禁使用平台禁忌词（速来、必看、最全、最强、免费送、薅羊毛、丑哭、踩雷等）
3. emoji优先用✨🔥✅💡❗️😭🤔💪，每个标题最多2个
4. 避免"XX分享""XX笔记"等无效词
5. 使用"亲测""试过""我发现"等真实感表述
6. 每个标题字数控制在20字以内

**正文创作要求（严格执行）**：
1. 开篇方法：金句开场/痛点切入/反转开场/故事引入（选择1种）
2. 文本结构：开头（emoji+金句1-2句）→ 主体（3-5个要点，每点前加emoji）→ 结尾（总结+互动引导）
3. 写作风格：像朋友聊天，真诚、直接、有温度
4. 句式要求：简单明了，一句话一个意思，每段2-3句话
5. 词汇选择：大白话优先，专业术语必须解释
6. 称呼使用："姐妹们"、"宝子们"等亲昵称呼
7. 语气词：多用"真的"、"绝了"、"爱了"等
8. 人称使用：多用"你、我、他"，少用"其、该、此、彼"
9. 顺序表达：用"第一、第二、第三"而不是"首先、其次、最后"
10. 互动引导：2-3处自然的互动问句（提问式/征集式/行动式/共鸣式）
11. 正文控制在600-800字之间

**写作约束（禁止）**：
1. 不使用破折号（——）
2. 禁用"A而且B"的对仗结构
3. 不使用冒号（：），除非是对话或列表
4. 开头不用设问句
5. 避免嵌套从句和复合句
6. 避免长句和书面语

**标签要求**：
提取5-10个标签，包含核心关键词、关联关键词、高转化词、热搜词
"""

    def _parse_result(self, result: str) -> Tuple[List[str], List[str]]:
        """
        解析生成结果

        Args:
            result: AI 生成的结果

        Returns:
            (标题列表, 标签列表) 元组
        """
        titles = []
        tags = []

        self.logger.debug(f"正在解析生成结果:\n{result}")

        # 提取标题（在"一. 标题"和"二. 正文"之间的内容）
        title_section_match = re.search(r'一[.、]\s*标题(.*?)二[.、]\s*正文', result, re.DOTALL)
        if title_section_match:
            title_section = title_section_match.group(1).strip()
            # 提取每一行非空内容作为标题
            for line in title_section.split('\n'):
                line = line.strip()
                # 移除可能的序号和标记
                line = re.sub(r'^\d+[.、)\]]\s*', '', line)
                line = re.sub(r'^\[标题\d+\]\s*', '', line)
                if line and not line.startswith('#'):
                    titles.append(line)

        # 如果上述方法未找到，尝试提取前几行作为标题
        if not titles:
            content_lines = result.split('\n')
            for line in content_lines[:10]:  # 只检查前10行
                line = line.strip()
                # 跳过明显的标记行
                if line and not line.startswith('#') and '正文' not in line and '标题' not in line and len(line) > 5:
                    # 移除可能的序号
                    line = re.sub(r'^\d+[.、)\]]\s*', '', line)
                    if line:
                        titles.append(line)
                        if len(titles) >= 5:  # 最多提取5个
                            break

        if titles:
            self.logger.info(f"提取到 {len(titles)} 个标题")
            for i, title in enumerate(titles[:3], 1):  # 只显示前3个
                self.logger.info(f"  标题{i}: {title[:50]}...")
        else:
            self.logger.warning("未能提取到标题")

        # 提取标签（在"标签："后面的内容）
        tag_matches = re.findall(r'#([^\s#]+)', result)
        if tag_matches:
            tags = tag_matches
            self.logger.info(f"提取到 {len(tags)} 个标签")
        else:
            self.logger.warning("未找到标签")

        return titles, tags

    def format_note(
        self,
        content: str,
        title: str,
        tags: List[str],
        images: List[str],
        all_titles: List[str] = None,
        score_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """格式化为可直接发小红书的纯文本（不是 markdown 文档）"""
        title = self._strip_markdown(title or "")
        body = self._strip_markdown(content or "")
        # 去掉正文末尾已有标签，避免重复
        body, body_tags = self._split_body_and_tags(body)
        final_tags = tags or body_tags
        seen = set()
        clean_tags = []
        for t in final_tags:
            t = str(t).strip().lstrip("#")
            if t and t not in seen:
                seen.add(t)
                clean_tags.append(t)

        parts = [title, "", body]
        if clean_tags:
            parts.append("")
            parts.append(" ".join(f"#{t}" for t in clean_tags))
        # 备选标题用纯文本附在末尾，方便用户挑选，不做成 markdown
        if all_titles and len(all_titles) > 1:
            parts.append("")
            parts.append("备选标题：")
            for i, t in enumerate(all_titles[1:5], 2):
                parts.append(f"{i}. {self._strip_markdown(t)}")
        return "\n".join(parts).strip()

    def _emphasize_body(self, body: str) -> str:
        """兼容旧调用：不再加 markdown 加粗。"""
        return self._strip_markdown(body)
