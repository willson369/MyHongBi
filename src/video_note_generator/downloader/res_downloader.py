"""
基于 res-downloader 设计的通用资源下载器

流程：
- 使用 yt-dlp 提取直链及必要请求头
- 若命中可下载的直链，则通过 HttpFileDownloader 多线程下载
- 作为对现有 yt-dlp 下载器的补充，增强对抖音 / TikTok 等平台的兼容性
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Optional, Tuple

import yt_dlp

from .base import BaseDownloader, DownloadError, VideoInfo
from .http_file_downloader import HttpFileDownloader, DownloadError as HttpDownloadError


def _safe_filename(text: str, default: str = "video") -> str:
    """移除文件名中的非法字符，并处理中文编码问题"""
    if not text:
        return default

    # 处理中文和特殊字符，确保文件名安全
    import unicodedata

    # 移除非法字符
    text = re.sub(r"[\\/*?\"<>|]", "", text)

    # 替换其他可能有问题的字符
    text = re.sub(r"[:]", "_", text)

    # 移除控制字符
    text = ''.join(char for char in text if not unicodedata.category(char).startswith('C'))

    # 清理首尾空格和点号
    text = text.strip(" .")

    # 确保文件名不为空且长度合理
    if not text or len(text) > 200:
        text = default

    # 如果包含中文字符，考虑添加时间戳以避免重复
    if any('\u4e00' <= char <= '\u9fff' for char in text):
        import time
        timestamp = str(int(time.time()))[-6:]  # 取时间戳后6位
        text = f"{text}_{timestamp}"

    return text


class ResDownloader(BaseDownloader):
    """借鉴 res-downloader 思路的通用下载器"""

    SUPPORTED_DOMAINS = [
        "douyin.com",
        "iesdouyin.com",
        "tiktok.com",
        "instagram.com",
        "facebook.com",
        "kuaishou.com",
        "weibo.com",
        "xhslink.com",
        "xiaohongshu.com",
    ]

    def __init__(
        self,
        logger=None,
        proxies: Optional[dict] = None,
        cookie_file: Optional[str] = None,
        max_workers: int = 4,
    ):
        super().__init__(logger)
        self.proxies = proxies
        self.cookie_file = cookie_file
        self.max_workers = max_workers

    # pylint: disable=unused-argument
    def supports(self, url: str) -> bool:
        return any(domain in url for domain in self.SUPPORTED_DOMAINS)

    def _extract_with_ytdlp(self, url: str) -> Tuple[dict, dict]:
        """使用 yt-dlp 提取下载信息和请求头"""
        # 预处理URL，尝试获取真实链接
        processed_url = self._preprocess_url(url)

        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
        }

        if self.cookie_file and Path(self.cookie_file).exists():
            ydl_opts["cookiefile"] = self.cookie_file

        if self.proxies and self.proxies.get("http://"):
            ydl_opts["proxy"] = self.proxies["http://"]

        # 尝试多种yt-dlp配置
        configs = [
            {},  # 默认配置
            {"extract_flat": False},  # 强制完整提取
            {"no_check_certificate": True},  # 忽略证书检查
            {"user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"},  # 移动端UA
        ]

        for i, config in enumerate(configs):
            try:
                ydl_opts.update(config)
                self.logger.debug(f"尝试配置 {i+1}/{len(configs)}: {list(config.keys())}")

                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(processed_url, download=False)

                if "entries" in info:
                    info = info["entries"][0]

                http_headers = info.get("http_headers") or {}
                self.logger.info(f"成功提取信息，使用配置 {i+1}")
                return info, http_headers

            except Exception as exc:
                self.logger.debug(f"配置 {i+1} 失败: {exc}")
                if i == len(configs) - 1:  # 最后一次尝试
                    raise

        raise DownloadError("所有提取策略都失败了", "generic", "extraction_failed")

    def _preprocess_url(self, url: str) -> str:
        """预处理URL，尝试获取真实的视频链接"""
        import re
        import requests

        # 如果是短链接，尝试重定向获取真实链接
        if any(domain in url for domain in ["douyin.com", "kuaishou.com", "xhslink.com"]):
            try:
                # 添加必要的头部信息
                headers = {
                    'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Language': 'zh-CN,zh;q=0.8,zh-TW;q=0.7,zh-HK;q=0.5,en-US;q=0.3,en;q=0.2',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                }

                # 对于抖音，添加特定的头部
                if "douyin.com" in url:
                    headers.update({
                        'Referer': 'https://www.douyin.com/',
                        'Cache-Control': 'no-cache',
                        'Pragma': 'no-cache',
                    })

                # 发送请求获取重定向后的URL
                response = requests.head(url, headers=headers, allow_redirects=True, timeout=10, verify=False)
                final_url = response.url

                if final_url != url:
                    self.logger.info(f"URL重定向: {url} -> {final_url}")
                    return final_url

            except Exception as exc:
                self.logger.debug(f"URL预处理失败: {exc}")

        return url

    def _download_direct(self, info: dict, headers: dict, output_dir: Path) -> Tuple[str, VideoInfo]:
        direct_url = info.get("url")
        if not direct_url or info.get("protocol", "").startswith("m3u8"):
            raise DownloadError("未获取到可直接下载的媒体地址", "generic", "direct_url_missing")

        ext = info.get("ext") or "mp4"
        title = _safe_filename(info.get("title", "video"))
        filename = f"{title}.{ext}"

        output_dir.mkdir(parents=True, exist_ok=True)
        target_path = output_dir / filename
        download_headers = headers.copy()
        if "Referer" not in download_headers and info.get("webpage_url"):
            download_headers["Referer"] = info["webpage_url"]

        downloader = HttpFileDownloader(
            direct_url,
            target_path,
            headers=download_headers,
            proxies=self.proxies,
            max_workers=self.max_workers,
        )

        def progress_callback(downloaded: int, total: Optional[int]) -> None:
            if total:
                percent = downloaded / total * 100
                self.logger.debug("下载进度 %.2f%%", percent)

        downloader.progress_callback = progress_callback

        try:
            file_path = downloader.download()
        except HttpDownloadError as exc:
            raise DownloadError(str(exc), "generic", "http_download_failed") from exc

        video_info = VideoInfo(
            title=info.get("title", ""),
            uploader=info.get("uploader", ""),
            description=info.get("description", ""),
            duration=int(info.get("duration", 0) or 0),
            platform=self._detect_platform(info.get("webpage_url", "")),
            url=info.get("webpage_url", direct_url),
            thumbnail_url=info.get("thumbnail"),
        )
        return str(file_path), video_info

    def _detect_platform(self, url: str) -> str:
        if not url:
            return "unknown"
        for domain in self.SUPPORTED_DOMAINS:
            if domain in url:
                if "douyin" in domain:
                    return "douyin"
                if "tiktok" in domain:
                    return "tiktok"
                if "instagram" in domain:
                    return "instagram"
                if "facebook" in domain:
                    return "facebook"
                if "kuaishou" in domain:
                    return "kuaishou"
                if "xiaohongshu" in domain or "xhslink" in domain:
                    return "xiaohongshu"
                if "weibo" in domain:
                    return "weibo"
        return "unknown"

    def _handle_error(self, exc: Exception, url: str) -> str:
        """
        智能错误处理，提供具体的解决建议

        Args:
            exc: 异常对象
            url: 原始URL

        Returns:
            用户友好的错误信息和解决建议
        """
        error_str = str(exc).lower()
        platform = self._detect_platform(url)

        if "fresh cookies" in error_str or "cookies" in error_str:
            return self._handle_cookie_error(platform, url, error_str)
        elif "sign in to confirm" in error_str or "bot" in error_str:
            return self._handle_bot_error(platform, url)
        elif "timeout" in error_str or "connection" in error_str:
            return self._handle_network_error(platform, url)
        elif "unsupported url" in error_str:
            return self._handle_unsupported_url_error(platform, url)
        else:
            return f"下载失败: {str(exc)}"

    def _handle_cookie_error(self, platform: str, url: str, error_str: str) -> str:
        """处理cookie相关错误"""
        if platform == "douyin":
            if "s_v_web_id" in error_str:
                return (
                    f"❌ 抖音认证失败：缺少关键cookie (s_v_web_id)\n\n"
                    f"🔧 解决方案：\n"
                    f"1. 在浏览器中登录抖音网页版\n"
                    f"2. 运行: python export_cookies.py\n"
                    f"3. 选择浏览器并完成授权\n"
                    f"4. 重新运行下载\n\n"
                    f"💡 当前cookies: {self.cookie_file or '未配置'}"
                )
            else:
                return (
                    f"❌ 抖音认证失败：cookies已过期\n\n"
                    f"🔧 解决方案：\n"
                    f"1. 确保浏览器已登录抖音\n"
                    f"2. 更新cookies: python export_cookies.py\n"
                    f"3. 或尝试直接访问: {url}\n\n"
                    f"💡 提示：抖音cookies需要定期更新"
                )
        elif platform == "xiaohongshu":
            return (
                f"❌ 小红书认证失败：cookies无效\n\n"
                f"🔧 解决方案：\n"
                f"1. 在浏览器登录小红书\n"
                f"2. 更新cookies: python export_cookies.py\n"
                f"3. 检查网络连接"
            )
        elif platform == "youtube":
            return (
                f"❌ YouTube认证失败：需要登录验证\n\n"
                f"🔧 解决方案：\n"
                f"1. 在浏览器登录YouTube/Google\n"
                f"2. 更新cookies: python export_cookies.py\n"
                f"3. 或暂时跳过此视频"
            )
        else:
            return (
                f"❌ {platform.title()}认证失败：需要更新cookies\n\n"
                f"🔧 解决方案：\n"
                f"1. 在浏览器登录对应平台\n"
                f"2. 运行: python export_cookies.py\n"
                f"3. 选择浏览器导出cookies"
            )

    def _handle_bot_error(self, platform: str, url: str) -> str:
        """处理反爬虫/机器人检测错误"""
        return (
            f"🤖 {platform.title()}反爬虫检测：需要验证身份\n\n"
            f"🔧 解决方案：\n"
            f"1. 更新cookies: python export_cookies.py\n"
            f"2. 更换网络环境（VPN/代理）\n"
            f"3. 等待一段时间后重试\n"
            f"4. 在浏览器中手动访问链接验证"
        )

    def _handle_network_error(self, platform: str, url: str) -> str:
        """处理网络连接错误"""
        return (
            f"🌐 网络连接失败：无法访问{platform.title()}\n\n"
            f"🔧 解决方案：\n"
            f"1. 检查网络连接\n"
            f"2. 配置代理（如果需要）\n"
            f"3. 稍后重试\n"
            f"4. 检查防火墙设置"
        )

    def _handle_unsupported_url_error(self, platform: str, url: str) -> str:
        """处理不支持的URL错误"""
        suggestions = {
            "douyin": "确保链接格式正确：https://www.douyin.com/video/xxxxx",
            "xiaohongshu": "确保链接格式正确：https://www.xiaohongshu.com/explore/xxxxx",
            "youtube": "确保链接格式正确：https://www.youtube.com/watch?v=xxxxx",
        }

        suggestion = suggestions.get(platform, "检查链接格式是否正确")

        return (
            f"❌ 不支持的{platform.title()}链接格式\n\n"
            f"🔧 建议：\n"
            f"{suggestion}\n"
            f"或尝试其他下载方法"
        )

    def download(
        self,
        url: str,
        output_dir: Path,
        audio_only: bool = True,
    ) -> Tuple[Optional[str], Optional[VideoInfo]]:
        output_dir = Path(output_dir)

        # 多策略下载：尝试不同的配置和方法
        strategies = [
            ("res_downloader", self._try_res_download),
            ("fallback_ytdlp", self._try_ytdlp_fallback),
        ]

        last_error = None
        for strategy_name, strategy_func in strategies:
            try:
                self.logger.info(f"尝试策略 {strategy_name}: {url}")
                result = strategy_func(url, output_dir, audio_only)
                if result and result[0]:  # 成功获得文件路径
                    self.logger.info(f"策略 {strategy_name} 成功")
                    return result
            except Exception as exc:  # pylint: disable=broad-except
                self.logger.warning(f"策略 {strategy_name} 失败: {exc}")
                last_error = exc
                continue

        # 所有策略都失败，提供用户友好的错误信息
        if last_error:
            error_msg = self._handle_error(last_error, url)
            raise DownloadError(error_msg, "generic", "all_strategies_failed", str(last_error)) from last_error
        else:
            raise DownloadError(f"所有下载策略都失败了: {url}", "generic", "all_strategies_failed")

    def _try_res_download(self, url: str, output_dir: Path, audio_only: bool) -> Tuple[Optional[str], Optional[VideoInfo]]:
        """尝试使用ResDownloader的主要下载方法"""
        info, headers = self._extract_with_ytdlp(url)

        # 若存在多种格式，优先选择音频
        if audio_only:
            requested_format = info.get("requested_formats")
            if requested_format:
                # 尝试获取音频流直链
                audio_stream = None
                for stream in requested_format:
                    if stream.get("acodec", "none") != "none":
                        audio_stream = stream
                        break
                if audio_stream and audio_stream.get("url"):
                    info = {**info, **audio_stream}

        file_path, video_info = self._download_direct(info, headers, output_dir)

        if audio_only and file_path and not file_path.endswith(".mp3"):
            # 若需要音频但抓到视频，将其交给 ffmpeg 转换
            audio_path = Path(file_path).with_suffix(".mp3")
            self.logger.info("正在提取音频轨 %s -> %s", file_path, audio_path)
            try:
                self._extract_audio(file_path, audio_path)
                return str(audio_path), video_info
            except Exception as exc:  # pylint: disable=broad-except
                # 转音频失败则返回原文件
                self.logger.warning("音频提取失败，将返回原文件: %s", exc)

        return file_path, video_info

    def _try_ytdlp_fallback(self, url: str, output_dir: Path, audio_only: bool) -> Tuple[Optional[str], Optional[VideoInfo]]:
        """使用yt-dlp直接下载的备用策略"""
        import yt_dlp

        # 构建yt-dlp选项
        ydl_opts = {
            "quiet": True,
            "no_warnings": True,
            "outtmpl": str(output_dir / "%(title)s.%(ext)s"),
            "format": (
                "bestaudio/best"
                if audio_only
                else (
                    "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/"
                    "best[height<=720][ext=mp4]/best[height<=720]/best"
                )
            ),
            "merge_output_format": "mp4",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }] if audio_only else [],
        }

        if self.cookie_file and Path(self.cookie_file).exists():
            ydl_opts["cookiefile"] = self.cookie_file

        if self.proxies and self.proxies.get("http://"):
            ydl_opts["proxy"] = self.proxies["http://"]

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)

                if info:
                    # 构建VideoInfo
                    video_info = VideoInfo(
                        title=info.get("title", ""),
                        uploader=info.get("uploader", ""),
                        description=info.get("description", ""),
                        duration=int(info.get("duration", 0) or 0),
                        platform=self._detect_platform(url),
                        url=url,
                        thumbnail_url=info.get("thumbnail"),
                    )

                    # 获取下载的文件路径
                    downloaded_file = ydl.prepare_filename(info)
                    if audio_only and not downloaded_file.endswith(".mp3"):
                        downloaded_file = str(Path(downloaded_file).with_suffix(".mp3"))

                    return downloaded_file, video_info

        except Exception as exc:
            raise DownloadError(f"yt-dlp备用下载失败: {str(exc)}", "generic", "ytdlp_fallback_failed") from exc

    def _extract_audio(self, input_file: str, output_file: Path) -> None:
        import subprocess

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            input_file,
            "-vn",
            "-acodec",
            "mp3",
            str(output_file),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg 提取音频失败: {result.stderr[:200]}")
        # 转换成功后可以清理原文件的副本避免空间占用
        try:
            os.remove(input_file)
        except OSError:
            pass

