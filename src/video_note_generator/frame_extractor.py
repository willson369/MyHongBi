"""
视频真实画面截帧

流程：多抽帧 → 感知哈希去重 → 规则粗筛 → 视觉 API 评选 3–9 张
B站优先用公开「高能进度条」弹幕密度峰值；其他平台均匀+场景变化抽帧。
只输出原画面（可裁黑边），绝不叠字。
"""
from __future__ import annotations

import base64
import json
import logging
import math
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import requests
from PIL import Image, ImageFilter, ImageOps, ImageStat

try:
    RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # Pillow < 9.1
    RESAMPLE = Image.LANCZOS

VIDEO_EXTS = {".mp4", ".flv", ".mkv", ".webm", ".mov", ".avi", ".m4v"}


@dataclass
class FrameCandidate:
    path: Path
    timestamp: float
    score_rule: float = 0.0
    phash: int = 0


class FrameExtractor:
    """从完整视频中截取适合发小红书的真实画面。"""

    def __init__(
        self,
        ai_processor,
        ffmpeg_path: Optional[str] = None,
        vision_model: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.ai = ai_processor
        self.ffmpeg = ffmpeg_path or "ffmpeg"
        self.ffprobe = self._guess_ffprobe(self.ffmpeg)
        self.vision_model = vision_model or getattr(ai_processor, "model", None)
        self.logger = logger or logging.getLogger(__name__)

    @staticmethod
    def _guess_ffprobe(ffmpeg: str) -> str:
        p = Path(ffmpeg)
        name = p.name.lower()
        if "ffmpeg" in name:
            probe = p.with_name(name.replace("ffmpeg", "ffprobe"))
            if probe.exists():
                return str(probe)
        return "ffprobe"

    def extract_for_note(
        self,
        video_path: Path,
        output_dir: Path,
        url: str = "",
        platform: str = "",
        duration: Optional[float] = None,
        prefix: str = "frame",
    ) -> List[str]:
        """主入口：返回最终选中的截图绝对路径列表。"""
        video_path = Path(video_path)
        if not video_path.exists():
            self.logger.error(f"视频文件不存在: {video_path}")
            return []

        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir = output_dir / "_candidates"
        work_dir.mkdir(parents=True, exist_ok=True)

        duration = duration or self._probe_duration(video_path) or 60.0
        target_count = self._adaptive_count(duration)

        timestamps = self.plan_with_video(url, platform, duration, video_path)
        self.logger.info(
            f"截帧计划: 时长={duration:.1f}s, 候选时刻={len(timestamps)}, 目标出图={target_count}"
        )

        raw_paths = self._grab_frames(video_path, timestamps, work_dir)
        if not raw_paths:
            self.logger.warning("ffmpeg 截帧失败，尝试均匀兜底")
            timestamps = self._uniform_timestamps(duration, n=12)
            raw_paths = self._grab_frames(video_path, timestamps, work_dir)
        if not raw_paths:
            return []

        candidates = []
        for path, ts in raw_paths:
            cropped = self._crop_letterbox(path)
            if cropped is None:
                continue
            rule = self._rule_score(cropped)
            if rule < 0.25:
                continue
            candidates.append(
                FrameCandidate(
                    path=cropped,
                    timestamp=ts,
                    score_rule=rule,
                    phash=self._dhash(cropped),
                )
            )

        candidates = self._dedupe(candidates, max_hamming=8)
        candidates.sort(key=lambda c: c.score_rule, reverse=True)
        # 规则筛到约 8–12 张再交给视觉模型
        shortlist = candidates[:12]
        if not shortlist:
            self.logger.warning("规则粗筛后无可用帧")
            return []

        picked = self._vision_pick(shortlist, target_count=target_count)
        if not picked:
            picked = shortlist[:target_count]

        final_paths: List[str] = []
        for i, cand in enumerate(picked, 1):
            dest = output_dir / f"{prefix}_{i:02d}.jpg"
            Image.open(cand.path).convert("RGB").save(dest, "JPEG", quality=92)
            final_paths.append(str(dest.resolve()))

        # 清理候选目录
        try:
            import shutil

            shutil.rmtree(work_dir, ignore_errors=True)
        except Exception:
            pass

        self.logger.info(f"最终输出 {len(final_paths)} 张真实截帧")
        return final_paths

    # ---------- 时刻规划 ----------

    def _plan_timestamps(
        self, url: str, platform: str, duration: float
    ) -> List[float]:
        plat = (platform or "").lower()
        is_bili = "bilibili" in plat or "bilibili.com" in (url or "") or "b23.tv" in (
            url or ""
        )
        if is_bili:
            peaks = self._bilibili_heat_peaks(url, duration)
            if peaks:
                # 峰值优先 + 少量均匀兜底，合计约 15–30
                uniform = self._uniform_timestamps(duration, n=8)
                merged = sorted(set(peaks + uniform))
                return self._clamp_timestamps(merged, duration)[:30]

        # 其他平台 / B站无峰值：均匀 + 场景变化
        uniform = self._uniform_timestamps(duration, n=18)
        scenes = self._scene_change_timestamps(url=None, duration=duration, video_hint=None)
        # 场景检测需要视频路径，在外层传入时用；这里仅均匀
        return self._clamp_timestamps(uniform, duration)

    def plan_with_video(
        self, url: str, platform: str, duration: float, video_path: Path
    ) -> List[float]:
        plat = (platform or "").lower()
        is_bili = "bilibili" in plat or "bilibili.com" in (url or "")
        if is_bili:
            peaks = self._bilibili_heat_peaks(url, duration)
            if peaks:
                uniform = self._uniform_timestamps(duration, n=8)
                return self._clamp_timestamps(sorted(set(peaks + uniform)), duration)[:30]

        uniform = self._uniform_timestamps(duration, n=16)
        scenes = self._detect_scenes(video_path, duration, max_points=12)
        return self._clamp_timestamps(sorted(set(uniform + scenes)), duration)[:28]

    def _adaptive_count(self, duration: float) -> int:
        if duration < 45:
            return 3
        if duration < 120:
            return 4
        if duration < 300:
            return 6
        if duration < 600:
            return 7
        return 9

    def _uniform_timestamps(self, duration: float, n: int = 16) -> List[float]:
        if duration <= 2:
            return [max(0.1, duration * 0.5)]
        # 避开片头片尾各 ~5%
        start = max(0.5, duration * 0.05)
        end = max(start + 0.5, duration * 0.95)
        if n <= 1:
            return [(start + end) / 2]
        step = (end - start) / (n - 1)
        return [start + i * step for i in range(n)]

    def _clamp_timestamps(self, timestamps: Sequence[float], duration: float) -> List[float]:
        out = []
        for t in timestamps:
            t = float(t)
            if math.isnan(t) or t < 0:
                continue
            t = min(max(0.2, t), max(0.2, duration - 0.3))
            out.append(round(t, 2))
        # 最小间隔 0.8s
        out.sort()
        filtered = []
        for t in out:
            if not filtered or t - filtered[-1] >= 0.8:
                filtered.append(t)
        return filtered

    def _bilibili_heat_peaks(self, url: str, duration: float) -> List[float]:
        """公开弹幕密度 API（高能进度条同源数据），无需登录。"""
        try:
            bvid = self._extract_bvid(url)
            if not bvid:
                return []
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ),
                "Referer": "https://www.bilibili.com",
            }
            view = requests.get(
                "https://api.bilibili.com/x/web-interface/view",
                params={"bvid": bvid},
                headers=headers,
                timeout=15,
            )
            view.raise_for_status()
            vdata = view.json().get("data") or {}
            aid = vdata.get("aid")
            if not aid:
                return []

            resp = requests.get(
                "https://api.bilibili.com/x/v2/dm/ajax",
                params={"aid": aid},
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            payload = resp.json()
            densities = payload.get("data")
            if not isinstance(densities, list) or len(densities) < 4:
                self.logger.info("B站弹幕密度数据为空，回退均匀抽帧")
                return []

            values = [float(x) for x in densities]
            n = len(values)
            # 取相对峰值：高于均值+0.5*std，最多 12 个
            mean = sum(values) / n
            var = sum((x - mean) ** 2 for x in values) / n
            std = math.sqrt(var)
            threshold = mean + 0.4 * std
            indexed = sorted(enumerate(values), key=lambda iv: iv[1], reverse=True)
            peaks_idx = []
            for i, v in indexed:
                if v < threshold and len(peaks_idx) >= 3:
                    continue
                # 邻域去重
                if any(abs(i - j) < max(2, n // 40) for j in peaks_idx):
                    continue
                peaks_idx.append(i)
                if len(peaks_idx) >= 12:
                    break

            peaks_idx.sort()
            peaks = [(i + 0.5) / n * duration for i in peaks_idx]
            self.logger.info(f"B站高能峰值 {len(peaks)} 个（弹幕密度）")
            return peaks
        except Exception as e:
            self.logger.warning(f"拉取 B站高能进度失败: {e}")
            return []

    @staticmethod
    def _extract_bvid(url: str) -> Optional[str]:
        if not url:
            return None
        m = re.search(r"(BV[\w]+)", url, re.I)
        return m.group(1) if m else None

    def _detect_scenes(
        self, video_path: Path, duration: float, max_points: int = 12
    ) -> List[float]:
        """用 ffmpeg select=gt(scene) 找场景切换点。"""
        try:
            cmd = [
                self.ffmpeg,
                "-hide_banner",
                "-i",
                str(video_path),
                "-filter:v",
                "select='gt(scene,0.35)',showinfo",
                "-vsync",
                "vfr",
                "-f",
                "null",
                "-",
            ]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
            times = []
            for line in (result.stderr or "").splitlines():
                m = re.search(r"pts_time:([0-9.]+)", line)
                if m:
                    times.append(float(m.group(1)))
            times = [t for t in times if 0.5 < t < duration - 0.5]
            # 均匀抽样最多 max_points
            if len(times) > max_points:
                step = len(times) / max_points
                times = [times[int(i * step)] for i in range(max_points)]
            return times
        except Exception as e:
            self.logger.debug(f"场景检测跳过: {e}")
            return []

    def _scene_change_timestamps(self, url, duration, video_hint) -> List[float]:
        return []

    # ---------- ffmpeg 截帧 ----------

    def _probe_duration(self, video_path: Path) -> Optional[float]:
        try:
            cmd = [
                self.ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(video_path),
            ]
            r = subprocess.run(
                cmd, capture_output=True, text=True, timeout=30, encoding="utf-8"
            )
            if r.returncode == 0 and r.stdout.strip():
                return float(r.stdout.strip())
        except Exception as e:
            self.logger.debug(f"ffprobe 失败: {e}")
        return None

    def _grab_frames(
        self, video_path: Path, timestamps: Sequence[float], work_dir: Path
    ) -> List[Tuple[Path, float]]:
        out: List[Tuple[Path, float]] = []
        for i, ts in enumerate(timestamps):
            dest = work_dir / f"raw_{i:03d}_{ts:.2f}.jpg"
            ok = self._ffmpeg_frame(video_path, ts, dest)
            if ok:
                out.append((dest, float(ts)))
        return out

    def _ffmpeg_frame(self, video_path: Path, ts: float, dest: Path) -> bool:
        try:
            cmd = [
                self.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-ss",
                f"{ts:.3f}",
                "-i",
                str(video_path),
                "-frames:v",
                "1",
                "-q:v",
                "2",
                "-y",
                str(dest),
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=60)
            return r.returncode == 0 and dest.exists() and dest.stat().st_size > 1000
        except Exception as e:
            self.logger.debug(f"截帧失败 @{ts}: {e}")
            return False

    # ---------- 规则筛 / 去重 / 裁黑边 ----------

    def _crop_letterbox(self, path: Path) -> Optional[Path]:
        try:
            img = Image.open(path).convert("RGB")
            w, h = img.size
            # 检测上下黑边
            pixels = img.load()

            def row_is_dark(y: int, thr: int = 18) -> bool:
                dark = 0
                step = max(1, w // 80)
                for x in range(0, w, step):
                    r, g, b = pixels[x, y]
                    if r + g + b < thr * 3:
                        dark += 1
                return dark / max(1, (w // step)) > 0.92

            def col_is_dark(x: int, thr: int = 18) -> bool:
                dark = 0
                step = max(1, h // 80)
                for y in range(0, h, step):
                    r, g, b = pixels[x, y]
                    if r + g + b < thr * 3:
                        dark += 1
                return dark / max(1, (h // step)) > 0.92

            top, bottom = 0, h
            while top < h // 3 and row_is_dark(top):
                top += 1
            while bottom > h * 2 // 3 and row_is_dark(bottom - 1):
                bottom -= 1
            left, right = 0, w
            while left < w // 3 and col_is_dark(left):
                left += 1
            while right > w * 2 // 3 and col_is_dark(right - 1):
                right -= 1

            if right - left < w * 0.5 or bottom - top < h * 0.5:
                cropped = img
            else:
                cropped = img.crop((left, top, right, bottom))

            out = path.with_name(path.stem + "_crop.jpg")
            cropped.save(out, "JPEG", quality=92)
            return out
        except Exception as e:
            self.logger.debug(f"裁黑边失败: {e}")
            return path if path.exists() else None

    def _rule_score(self, path: Path) -> float:
        try:
            img = Image.open(path).convert("RGB")
            gray = ImageOps.grayscale(img)
            stat = ImageStat.Stat(gray)
            mean = stat.mean[0] / 255.0
            # 过暗/过亮惩罚
            brightness = 1.0 - abs(mean - 0.5) * 2.0
            # 对比度：标准差
            contrast = min(1.0, (stat.stddev[0] / 64.0))
            # 清晰度：拉普拉斯近似（边缘强度）
            edges = gray.filter(ImageFilter.FIND_EDGES)
            sharp = min(1.0, ImageStat.Stat(edges).mean[0] / 40.0)
            # 近似黑帧
            if mean < 0.08 or mean > 0.95:
                return 0.0
            if contrast < 0.08:
                return 0.05
            return max(0.0, 0.35 * brightness + 0.30 * contrast + 0.35 * sharp)
        except Exception:
            return 0.0

    def _dhash(self, path: Path, hash_size: int = 8) -> int:
        img = Image.open(path).convert("L").resize(
            (hash_size + 1, hash_size), RESAMPLE
        )
        pixels = list(img.getdata())
        bits = 0
        for row in range(hash_size):
            for col in range(hash_size):
                left = pixels[row * (hash_size + 1) + col]
                right = pixels[row * (hash_size + 1) + col + 1]
                bits = (bits << 1) | (1 if left > right else 0)
        return bits

    @staticmethod
    def _hamming(a: int, b: int) -> int:
        return bin(a ^ b).count("1")

    def _dedupe(
        self, candidates: List[FrameCandidate], max_hamming: int = 8
    ) -> List[FrameCandidate]:
        kept: List[FrameCandidate] = []
        for c in sorted(candidates, key=lambda x: x.score_rule, reverse=True):
            if any(self._hamming(c.phash, k.phash) <= max_hamming for k in kept):
                continue
            kept.append(c)
        return kept

    # ---------- 视觉评选 ----------

    def _vision_pick(
        self, candidates: List[FrameCandidate], target_count: int
    ) -> List[FrameCandidate]:
        try:
            # 限制送入模型的数量与体积
            batch = candidates[:12]
            content = [
                {
                    "type": "text",
                    "text": (
                        f"你是小红书封面/配图编辑。下面是同一条视频的真实截帧候选。"
                        f"请选出最适合发小红书的 {target_count} 张（可少不可多滥）。\n"
                        "标准：画面清晰、主体明确、有信息量或情绪张力、适合当封面或配图；"
                        "避免黑屏/糊/字幕墙占满/纯静态白板/重复构图。\n"
                        "只返回 JSON：{\"indexes\":[1-based序号,...],\"cover\":首选封面序号}\n"
                        "不要解释。"
                    ),
                }
            ]
            for i, c in enumerate(batch, 1):
                b64 = self._image_to_b64_jpeg(c.path, max_side=768)
                content.append({"type": "text", "text": f"候选图 #{i} @ {c.timestamp:.1f}s"})
                content.append(
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    }
                )

            model = self.vision_model or self.ai.model
            response = self.ai.client.chat.completions.create(
                model=model,
                messages=[
                    {
                        "role": "system",
                        "content": "你只输出合法 JSON，不要 markdown。",
                    },
                    {"role": "user", "content": content},
                ],
                temperature=0.2,
                max_tokens=300,
            )
            text = (response.choices[0].message.content or "").strip()
            text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.I | re.M).strip()
            data = json.loads(text)
            indexes = data.get("indexes") or []
            cover = data.get("cover")
            picked: List[FrameCandidate] = []
            seen = set()
            ordered = []
            if cover:
                ordered.append(int(cover))
            ordered.extend(int(x) for x in indexes)
            for idx in ordered:
                if idx < 1 or idx > len(batch) or idx in seen:
                    continue
                seen.add(idx)
                picked.append(batch[idx - 1])
                if len(picked) >= target_count:
                    break
            if picked:
                self.logger.info(f"视觉模型选出 {len(picked)} 张")
                return picked
        except Exception as e:
            self.logger.warning(f"视觉评选失败，回退规则排序: {e}")
        return []

    @staticmethod
    def _image_to_b64_jpeg(path: Path, max_side: int = 768) -> str:
        img = Image.open(path).convert("RGB")
        w, h = img.size
        scale = min(1.0, max_side / max(w, h))
        if scale < 1.0:
            img = img.resize((int(w * scale), int(h * scale)), RESAMPLE)
        from io import BytesIO

        buf = BytesIO()
        img.save(buf, format="JPEG", quality=80)
        return base64.b64encode(buf.getvalue()).decode("ascii")


def find_video_file(directory: Path) -> Optional[Path]:
    """在目录中找最近的视频文件。"""
    directory = Path(directory)
    if not directory.exists():
        return None
    files = [
        p
        for p in directory.rglob("*")
        if p.is_file() and p.suffix.lower() in VIDEO_EXTS and p.stat().st_size > 50_000
    ]
    if not files:
        return None
    return max(files, key=lambda p: p.stat().st_mtime)
