"""
视频笔记生成处理器
"""
import shutil
from pathlib import Path
from typing import List, Optional
from datetime import datetime
import logging
import subprocess

from .config import Settings
from .downloader import (
    DownloaderRegistry,
    YtDlpDownloader,
    BilibiliDownloader,
    ResDownloader,
    VideoInfo,
)
from .transcriber import WhisperTranscriber
from .ai_processor import AIProcessor
from .generators.xiaohongshu import XiaohongshuGenerator
from .generators.blog import BlogGenerator
from .image_service import UnsplashImageService
from .subtitle_extractor import SubtitleExtractor
from .frame_extractor import FrameExtractor, find_video_file, VIDEO_EXTS


class VideoNoteProcessor:
    """视频笔记处理器"""

    def __init__(self, settings: Settings, logger: logging.Logger):
        """
        初始化处理器

        Args:
            settings: 配置对象
            logger: 日志记录器
        """
        self.settings = settings
        self.logger = logger

        # 初始化下载器注册表
        self.downloader_registry = DownloaderRegistry()

        # 注册 Bilibili 专用下载器（优先级高，先注册）
        bilibili_downloader = BilibiliDownloader(
            logger=logger,
            cookie_file=settings.cookie_file
        )
        self.downloader_registry.register(bilibili_downloader)

        # 注册基于 res-downloader 思路的通用下载器（抖音/小红书等）
        res_downloader = ResDownloader(
            logger=logger,
            proxies=settings.get_proxies(),
            cookie_file=settings.cookie_file
        )
        self.downloader_registry.register(res_downloader)

        # 注册通用下载器（作为最终兜底）
        ytdlp_downloader = YtDlpDownloader(
            logger=logger,
            proxies=settings.get_proxies(),
            cookie_file=settings.cookie_file
        )
        self.downloader_registry.register(ytdlp_downloader)

        # 初始化转录器
        self.transcriber = WhisperTranscriber(
            logger=logger,
            cache_dir=settings.cache_dir / "transcriptions"
        )

        # 初始化字幕提取器
        self.subtitle_extractor = SubtitleExtractor()

        # 初始化 AI 处理器
        self.ai_processor = AIProcessor(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_api_url,
            model=settings.ai_model,
            app_name=settings.openrouter_app_name,
            http_referer=settings.openrouter_http_referer,
            logger=logger
        )

        # 初始化生成器
        self.xiaohongshu_generator = XiaohongshuGenerator(
            ai_processor=self.ai_processor,
            logger=logger
        )

        self.blog_generator = BlogGenerator(
            ai_processor=self.ai_processor,
            logger=logger
        )

        # 初始化图片服务（仅作截帧失败时的最后兜底）
        self.image_service = None
        if settings.unsplash_access_key:
            self.image_service = UnsplashImageService(
                access_key=settings.unsplash_access_key,
                logger=logger
            )

        ffmpeg = settings.ffmpeg_path or "ffmpeg"
        self.frame_extractor = FrameExtractor(
            ai_processor=self.ai_processor,
            ffmpeg_path=ffmpeg,
            vision_model=settings.vision_model or settings.ai_model,
            logger=logger,
        )
        self.last_xhs_images: List[str] = []
        self.last_xhs_note: str = ""
        self.last_xhs_score = None
        self.last_xhs_title: str = ""
        self.last_xhs_body: str = ""
        self.last_xhs_tags: List[str] = []

    def process_video(
        self,
        url: str,
        generate_xiaohongshu: bool = True,
        generate_blog: bool = True,
        category: str = "职场吐槽",
        style_reference: str = "",
    ) -> List[Path]:
        """
        处理视频

        Args:
            url: 视频URL
            generate_xiaohongshu: 是否生成小红书版本
            generate_blog: 是否生成博客
            category: 小红书品类模板
            style_reference: 用户爆款参考文案

        Returns:
            生成的文件路径列表
        """
        self.logger.info(f"开始处理视频: {url}")
        self._xhs_category = category
        self._xhs_style_reference = style_reference
        self.last_xhs_images = []
        self.last_xhs_note = ""
        self.last_xhs_score = None
        self.last_xhs_title = ""
        self.last_xhs_body = ""
        self.last_xhs_tags = []
        generated_files = []

        # 创建临时目录
        temp_dir = self.settings.output_dir / "temp"
        temp_dir.mkdir(parents=True, exist_ok=True)

        video_path: Optional[Path] = None

        try:
            # Tier 1: 尝试提取官方字幕（最快，免费，1-5秒）
            self.logger.info("🎯 策略1: 尝试提取官方字幕...")
            transcript = self.subtitle_extractor.extract(url)

            if transcript:
                self.logger.info(f"✅ 使用官方字幕（{len(transcript)}字符，耗时<5秒）")
                video_info = self._get_video_info_without_download(url)
                if not video_info:
                    self.logger.warning("无法获取视频信息，使用默认信息")
                    video_info = VideoInfo(
                        title="视频标题",
                        duration=0,
                        uploader="未知",
                        description="",
                        platform="未知",
                        url=url,
                    )
            else:
                self.logger.info("❌ 未找到官方字幕")
                video_info = None

            # 需要截帧或 Whisper：下载完整视频（不只音频）
            need_media = generate_xiaohongshu or not transcript
            if need_media:
                self.logger.info("正在下载完整视频（用于真实截帧/转写）...")
                media_path, downloaded_info = self.downloader_registry.download(
                    url=url,
                    output_dir=temp_dir,
                    audio_only=False,
                )
                if downloaded_info:
                    video_info = downloaded_info
                if media_path:
                    media_path = Path(media_path)
                    if media_path.suffix.lower() in VIDEO_EXTS:
                        video_path = media_path
                    else:
                        video_path = find_video_file(temp_dir)
                        if not video_path and media_path.exists():
                            # 可能只下到了音频，再试一次强制找视频
                            video_path = find_video_file(temp_dir)

                if not video_path:
                    video_path = find_video_file(temp_dir)

                if not video_path and not transcript:
                    self.logger.error("视频下载失败且无字幕可用")
                    return generated_files

                if video_path:
                    self.logger.info(f"视频文件就绪: {video_path.name}")

            if not video_info:
                video_info = VideoInfo(
                    title="视频标题",
                    duration=0,
                    uploader="未知",
                    description="",
                    platform="未知",
                    url=url,
                )

            # 无字幕则从视频抽音频再 Whisper
            if not transcript:
                if not video_path:
                    self.logger.error("无字幕且无视频文件，无法转写")
                    return generated_files
                self.logger.info("🎤 从视频提取音频并用 Whisper 转写...")
                audio_path = self._extract_audio(video_path, temp_dir)
                if not audio_path:
                    self.logger.error("音频提取失败")
                    return generated_files
                transcript = self.transcriber.transcribe(
                    audio_path=audio_path,
                    model_name=self.settings.whisper_model,
                    language="zh",
                )
                if not transcript:
                    self.logger.error("音频转录失败")
                    return generated_files
                self.logger.info(f"转录完成，文本长度: {len(transcript)} 字符")

            # 3. 保存原始转录
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_file = self._save_original_note(
                video_info=video_info,
                transcript=transcript,
                timestamp=timestamp,
            )
            generated_files.append(original_file)

            # 4. 整理内容（仅博客路径 / 本地留存；小红书直接用原转录改写）
            organized_content = transcript
            if generate_blog:
                self.logger.info("正在整理博客长文...")
                organized_content = self.ai_processor.organize_long_content(
                    content=transcript,
                    chunk_size=self.settings.content_chunk_size,
                )
                organized_file = self._save_organized_note(
                    video_info=video_info,
                    content=organized_content,
                    timestamp=timestamp,
                )
                generated_files.append(organized_file)

            # 5. 生成小红书版本（主交付：网感文案 + 真实截帧）
            xhs_outputs: List[Path] = []
            if generate_xiaohongshu:
                self.logger.info("正在生成小红书图文（真实截帧）...")
                xiaohongshu_file = self._generate_xiaohongshu_note(
                    content=transcript,
                    timestamp=timestamp,
                    video_path=video_path,
                    video_info=video_info,
                    url=url,
                )
                if xiaohongshu_file:
                    xhs_outputs = [xiaohongshu_file] + [
                        Path(p) for p in self.last_xhs_images
                    ]
                    generated_files.extend(xhs_outputs)

            # 6. 博客可选
            if generate_blog:
                self.logger.info("正在生成博客文章...")
                blog_file = self._generate_blog_note(
                    content=organized_content,
                    video_info=video_info,
                    timestamp=timestamp,
                )
                if blog_file:
                    generated_files.append(blog_file)

            # 只把小红书笔记+配图返回给前端
            if xhs_outputs:
                self.logger.info(f"处理完成，返回小红书图文 {len(xhs_outputs)} 个文件")
                return xhs_outputs

            self.logger.info(f"处理完成，共生成 {len(generated_files)} 个文件")
            return generated_files

        except Exception as e:
            self.logger.error(f"处理视频时出错: {e}", exc_info=True)
            return generated_files

        finally:
            # 清理临时文件
            if temp_dir.exists():
                shutil.rmtree(temp_dir, ignore_errors=True)

    def _extract_audio(self, video_path: Path, output_dir: Path) -> Optional[str]:
        """从视频提取 mp3 音频供 Whisper 使用。"""
        try:
            ffmpeg = self.settings.ffmpeg_path or "ffmpeg"
            audio_path = Path(output_dir) / f"{video_path.stem}_audio.mp3"
            cmd = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-i",
                str(video_path),
                "-vn",
                "-acodec",
                "mp3",
                "-y",
                str(audio_path),
            ]
            r = subprocess.run(cmd, capture_output=True, timeout=600)
            if r.returncode == 0 and audio_path.exists():
                return str(audio_path)
            self.logger.error(f"ffmpeg 抽音频失败: {r.stderr}")
            return None
        except Exception as e:
            self.logger.error(f"抽音频异常: {e}")
            return None

    def _save_original_note(
        self,
        video_info: VideoInfo,
        transcript: str,
        timestamp: str
    ) -> Path:
        """保存原始笔记"""
        file_path = self.settings.output_dir / f"{timestamp}_original.md"

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"# {video_info.title}\n\n")
            f.write(f"## 视频信息\n")
            f.write(f"- 作者：{video_info.uploader}\n")
            f.write(f"- 时长：{video_info.duration}秒\n")
            f.write(f"- 平台：{video_info.platform}\n")
            f.write(f"- 链接：{video_info.url}\n\n")
            f.write(f"## 原始转录内容\n\n")
            f.write(transcript)

        self.logger.info(f"原始笔记已保存: {file_path}")
        return file_path

    def _save_organized_note(
        self,
        video_info: VideoInfo,
        content: str,
        timestamp: str
    ) -> Path:
        """保存整理版笔记"""
        file_path = self.settings.output_dir / f"{timestamp}_organized.md"

        with open(file_path, 'w', encoding='utf-8') as f:
            f.write(f"# {video_info.title} - 整理版\n\n")
            f.write(f"## 视频信息\n")
            f.write(f"- 作者：{video_info.uploader}\n")
            f.write(f"- 时长：{video_info.duration}秒\n")
            f.write(f"- 平台：{video_info.platform}\n")
            f.write(f"- 链接：{video_info.url}\n\n")
            f.write(f"## 内容整理\n\n")
            f.write(content)

        self.logger.info(f"整理版笔记已保存: {file_path}")
        return file_path

    def _generate_xiaohongshu_note(
        self,
        content: str,
        timestamp: str,
        video_path: Optional[Path] = None,
        video_info: Optional[VideoInfo] = None,
        url: str = "",
    ) -> Optional[Path]:
        """生成小红书笔记 + 视频真实截帧"""
        try:
            category = getattr(self, "_xhs_category", "职场吐槽")
            style_reference = getattr(self, "_xhs_style_reference", "")

            # 直接用视频原转录改写成网感文案（不再经博客整理版）
            xiaohongshu_content, titles, tags, score_meta = self.xiaohongshu_generator.generate(
                content=content,
                max_tokens=self.settings.max_tokens,
                category=category,
                style_reference=style_reference,
            )

            images: List[str] = []
            main_title = titles[0] if titles else "小红书笔记"

            # 真实截帧（绝不叠字）
            if video_path and Path(video_path).exists():
                try:
                    img_dir = self.settings.output_dir / "images" / timestamp
                    images = self.frame_extractor.extract_for_note(
                        video_path=Path(video_path),
                        output_dir=img_dir,
                        url=url or (video_info.url if video_info else ""),
                        platform=video_info.platform if video_info else "",
                        duration=float(video_info.duration) if video_info and video_info.duration else None,
                        prefix="frame",
                    )
                except Exception as img_err:
                    self.logger.error(f"真实截帧失败: {img_err}", exc_info=True)
            else:
                self.logger.warning("无视频文件，无法截取真实画面")

            if not images and self.image_service:
                self.logger.warning("截帧为空，尝试 Unsplash 兜底（非真实画面）")
                images = self.image_service.get_photos_for_xiaohongshu(
                    titles=titles,
                    tags=tags,
                    count=3,
                    ai_processor=self.ai_processor,
                    content=content,
                )

            self.last_xhs_images = images
            self.last_xhs_score = score_meta
            self.last_xhs_title = main_title
            self.last_xhs_body = xiaohongshu_content
            self.last_xhs_tags = tags

            if titles:
                formatted_content = self.xiaohongshu_generator.format_note(
                    content=xiaohongshu_content,
                    title=titles[0],
                    tags=tags,
                    images=images,
                    all_titles=None,
                    score_meta=None,
                )
                self.last_xhs_note = formatted_content

                file_path = self.settings.output_dir / f"{timestamp}_xiaohongshu.md"
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(formatted_content)

                meta_path = self.settings.output_dir / f"{timestamp}_xhs_score.json"
                import json
                with open(meta_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        **score_meta,
                        "title": main_title,
                        "body": xiaohongshu_content,
                        "tags": tags,
                        "images": images,
                    }, f, ensure_ascii=False, indent=2)

                self.logger.info(f"小红书笔记已保存: {file_path}")
                return file_path

            return None

        except Exception as e:
            self.logger.error(f"生成小红书笔记失败: {e}", exc_info=True)
            return None

    def _generate_blog_note(
        self,
        content: str,
        video_info: VideoInfo,
        timestamp: str
    ) -> Optional[Path]:
        """生成博客文章"""
        try:
            video_info_dict = {
                'title': video_info.title,
                'uploader': video_info.uploader,
                'url': video_info.url,
                'platform': video_info.platform,
                'timestamp': timestamp
            }

            blog_content = self.blog_generator.generate(
                content=content,
                video_info=video_info_dict,
                max_tokens=16000
            )

            if blog_content:
                formatted_blog = self.blog_generator.format_blog(
                    content=blog_content,
                    video_info=video_info_dict
                )

                file_path = self.settings.output_dir / f"{timestamp}_blog.md"
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(formatted_blog)

                self.logger.info(f"博客文章已保存: {file_path}")
                return file_path

            return None

        except Exception as e:
            self.logger.error(f"生成博客文章失败: {e}", exc_info=True)
            return None

    def _get_video_info_without_download(self, url: str) -> Optional[VideoInfo]:
        """
        获取视频信息（不下载视频）
        """
        try:
            import yt_dlp

            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'skip_download': True,
            }

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)

                if info:
                    platform = "未知"
                    if 'youtube.com' in url or 'youtu.be' in url:
                        platform = "YouTube"
                    elif 'bilibili.com' in url or 'b23.tv' in url:
                        platform = "Bilibili"
                    elif 'tiktok.com' in url:
                        platform = "TikTok"
                    elif 'douyin.com' in url:
                        platform = "Douyin"

                    return VideoInfo(
                        title=info.get('title', '未知标题'),
                        duration=info.get('duration', 0) or 0,
                        uploader=info.get('uploader', '未知'),
                        description=info.get('description', ''),
                        platform=platform,
                        url=url,
                        thumbnail_url=info.get('thumbnail'),
                    )
        except Exception as e:
            self.logger.warning(f"获取视频信息失败: {e}")
            return None

    def process_multiple_videos(
        self,
        urls: List[str],
        generate_xiaohongshu: bool = True
    ) -> dict:
        """
        批量处理视频
        """
        results = {}
        total = len(urls)

        for i, url in enumerate(urls, 1):
            self.logger.info(f"处理第 {i}/{total} 个视频")
            try:
                files = self.process_video(url, generate_xiaohongshu)
                results[url] = files
            except Exception as e:
                self.logger.error(f"处理视频失败: {url}, 错误: {e}")
                results[url] = []

        return results
