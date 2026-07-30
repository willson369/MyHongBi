#!/usr/bin/env python3
"""
视频笔记生成器 - FastAPI Web应用
"""
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field
from pathlib import Path
import sys
import logging
from datetime import datetime
from typing import List, Optional
import traceback
import asyncio
from concurrent.futures import ThreadPoolExecutor

# 添加src到路径
sys.path.insert(0, str(Path(__file__).parent / "src"))

from video_note_generator.config import Settings
from video_note_generator.processor import VideoNoteProcessor
from video_note_generator.utils.cookie_manager import CookieManager

# 创建FastAPI应用
app = FastAPI(
    title="红笔",
    description="视频一键变小红书爆款 · 网感分看得见",
    version="0.1.0"
)

# 挂载静态文件
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# 生成结果（配图可直接用 <img src="/outputs/..."> 预览）
outputs_dir = Path(__file__).parent / "generated_notes"
outputs_dir.mkdir(exist_ok=True)
(outputs_dir / "images").mkdir(exist_ok=True)
app.mount("/outputs", StaticFiles(directory=outputs_dir), name="outputs")


def _to_outputs_url(path) -> str:
    """本地 generated_notes 路径 → 浏览器可直接打开的 /outputs/..."""
    p = Path(path).resolve()
    root = outputs_dir.resolve()
    try:
        rel = p.relative_to(root).as_posix()
    except ValueError:
        s = str(p).replace("\\", "/")
        marker = "/generated_notes/"
        i = s.lower().rfind(marker)
        rel = s[i + len(marker) :] if i >= 0 else p.name
    return f"/outputs/{rel}"

# 模板配置
templates_dir = Path(__file__).parent / "templates"
templates_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=templates_dir)

# 日志配置
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 线程池用于处理视频（避免阻塞异步循环）
executor = ThreadPoolExecutor(max_workers=3)


# ========== 请求/响应模型 ==========

class VideoProcessRequest(BaseModel):
    url: str = Field(..., description="视频URL")
    generate_xiaohongshu: bool = Field(True, description="是否生成小红书笔记")
    generate_blog: bool = Field(False, description="是否生成博客文章")
    category: str = Field("职场吐槽", description="小红书品类")
    style_reference: str = Field("", description="用户爆款参考文案（可选）")


class VideoProcessResponse(BaseModel):
    success: bool
    message: str
    files: List[str] = []
    images: List[str] = []
    note: Optional[str] = None
    title: Optional[str] = None
    body: Optional[str] = None
    tags: List[str] = []
    score: Optional[dict] = None
    thesis: Optional[dict] = None
    error: Optional[str] = None


class BatchProcessRequest(BaseModel):
    urls: List[str] = Field(..., description="视频URL列表")
    generate_xiaohongshu: bool = Field(True, description="是否生成小红书笔记")
    generate_blog: bool = Field(False, description="是否生成博客文章")
    category: str = Field("职场吐槽", description="小红书品类")
    style_reference: str = Field("", description="用户爆款参考文案（可选）")


class ScoreRequest(BaseModel):
    title: str = Field("", description="标题")
    body: str = Field(..., description="正文")
    category: str = Field("职场吐槽", description="品类")


class BatchProcessResponse(BaseModel):
    total: int
    success_count: int
    failed_count: int
    results: List[VideoProcessResponse]


class ConfigCheckResponse(BaseModel):
    configured: bool
    message: str
    settings: Optional[dict] = None


# ========== 工具函数 ==========

def get_settings() -> Settings:
    """获取配置"""
    try:
        return Settings()
    except Exception as e:
        logger.error(f"配置加载失败: {e}")
        raise


def validate_url(url: str) -> bool:
    """验证URL格式"""
    url = url.strip()
    return url.startswith(('http://', 'https://')) and len(url) > 10


def process_video_sync(
    url: str,
    generate_xiaohongshu: bool,
    generate_blog: bool,
    settings: Settings,
    category: str = "职场吐槽",
    style_reference: str = "",
) -> VideoProcessResponse:
    """同步处理单个视频（在线程池中运行）"""
    try:
        logger.info(f"开始处理视频: {url}")

        # 创建处理器
        processor = VideoNoteProcessor(settings=settings, logger=logger)

        # 处理视频
        files = processor.process_video(
            url=url,
            generate_xiaohongshu=generate_xiaohongshu,
            generate_blog=generate_blog,
            category=category,
            style_reference=style_reference,
        )

        # 转换Path对象为字符串（统一正斜杠，方便前端下载）
        file_paths = [str(f).replace("\\", "/") for f in files]

        # 检查是否真的生成了文件
        if not files or len(files) == 0:
            logger.warning(f"视频处理完成但未生成任何文件: {url}")
            return VideoProcessResponse(
                success=False,
                message="处理失败：未生成任何文件",
                error=(
                    "视频处理失败，没有生成笔记。常见原因：\n"
                    "1) B站/抖音下载被拦（可配置 cookies 或确认代理可用）\n"
                    "2) 未安装/未找到 FFmpeg\n"
                    "3) 无字幕且 Whisper 转写失败\n"
                    "请查看服务端日志获取详细错误"
                )
            )

        # 读取评分与笔记正文
        score = getattr(processor, "last_xhs_score", None)
        if score and not isinstance(score, dict):
            try:
                score = score.to_dict() if hasattr(score, "to_dict") else dict(score)
            except Exception:
                score = None
        note = getattr(processor, "last_xhs_note", None) or None
        images = list(getattr(processor, "last_xhs_images", []) or [])
        title = getattr(processor, "last_xhs_title", None) or None
        body = getattr(processor, "last_xhs_body", None) or None
        tags = list(getattr(processor, "last_xhs_tags", []) or [])
        thesis = (score or {}).get("thesis") if isinstance(score, dict) else None
        try:
            import json
            from pathlib import Path as P
            for fp in files:
                p = P(fp)
                if p.name.endswith("_xiaohongshu.md"):
                    with open(p, "r", encoding="utf-8") as f:
                        note = f.read()
                    meta = p.with_name(p.name.replace("_xiaohongshu.md", "_xhs_score.json"))
                    if meta.exists():
                        with open(meta, "r", encoding="utf-8") as f:
                            file_score = json.load(f)
                            score = score or file_score
                            images = file_score.get("images") or images
                            title = file_score.get("title") or title
                            body = file_score.get("body") or body
                            tags = file_score.get("tags") or tags
                            thesis = file_score.get("thesis") or thesis
                elif p.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
                    images.append(str(p))
            # 去重并转成浏览器可直接 <img src> 的 URL
            seen = set()
            urls = []
            for i in images:
                u = _to_outputs_url(i)
                if u not in seen:
                    seen.add(u)
                    urls.append(u)
            images = urls
        except Exception:
            pass

        logger.info(f"视频处理成功: {url}, 生成 {len(files)} 个文件")

        return VideoProcessResponse(
            success=True,
            message=f"已生成小红书图文：笔记 + {len([i for i in images if i])} 张真实截帧",
            files=file_paths,
            images=images,
            note=note,
            title=title,
            body=body,
            tags=tags,
            score=score if isinstance(score, dict) else None,
            thesis=thesis if isinstance(thesis, dict) else None,
        )

    except Exception as e:
        error_msg = str(e)
        logger.error(f"处理视频失败: {url}\n{traceback.format_exc()}")

        return VideoProcessResponse(
            success=False,
            message="处理失败",
            error=error_msg
        )


# ========== API路由 ==========

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """返回主页面（禁止缓存，避免旧前端卡住）"""
    resp = templates.TemplateResponse(request, "index.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.get("/api/config/check", response_model=ConfigCheckResponse)
async def check_config():
    """检查配置状态"""
    try:
        settings = get_settings()

        # 检查API密钥是否配置
        api_configured = (
            settings.openrouter_api_key and
            settings.openrouter_api_key not in (
                "your-api-key-here",
                "your-openrouter-api-key-here",
            )
        )

        if api_configured:
            return ConfigCheckResponse(
                configured=True,
                message="API已配置",
                settings={
                    "ai_model": settings.ai_model,
                    "whisper_model": settings.whisper_model,
                    "output_dir": str(settings.output_dir)
                }
            )
        else:
            return ConfigCheckResponse(
                configured=False,
                message="请在.env文件中配置OPENROUTER_API_KEY"
            )

    except Exception as e:
        return ConfigCheckResponse(
            configured=False,
            message=f"配置检查失败: {str(e)}"
        )


@app.post("/api/process", response_model=VideoProcessResponse)
async def process_video(request: VideoProcessRequest):
    """处理单个视频"""
    try:
        # 验证URL
        if not validate_url(request.url):
            raise HTTPException(
                status_code=400,
                detail="无效的URL格式（需以http://或https://开头）"
            )

        # 获取配置
        settings = get_settings()

        # 在线程池中处理视频（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            executor,
            process_video_sync,
            request.url,
            request.generate_xiaohongshu,
            request.generate_blog,
            settings,
            request.category,
            request.style_reference,
        )

        return result

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API错误: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/batch-process", response_model=BatchProcessResponse)
async def batch_process(request: BatchProcessRequest):
    """批量处理视频"""
    try:
        # 验证所有URL
        invalid_urls = [url for url in request.urls if not validate_url(url)]
        if invalid_urls:
            raise HTTPException(
                status_code=400,
                detail=f"发现 {len(invalid_urls)} 个无效URL"
            )

        # 获取配置
        settings = get_settings()

        # 处理所有视频
        results = []
        loop = asyncio.get_event_loop()

        for url in request.urls:
            result = await loop.run_in_executor(
                executor,
                process_video_sync,
                url,
                request.generate_xiaohongshu,
                request.generate_blog,
                settings,
                request.category,
                request.style_reference,
            )
            results.append(result)

        # 统计结果
        success_count = sum(1 for r in results if r.success)
        failed_count = len(results) - success_count

        return BatchProcessResponse(
            total=len(request.urls),
            success_count=success_count,
            failed_count=failed_count,
            results=results
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"批量处理错误: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/download/{file_path:path}")
async def download_file(file_path: str):
    """下载生成的文件"""
    try:
        # 安全检查：确保文件在输出目录内
        settings = get_settings()
        full_path = Path(file_path)

        # 检查文件是否存在
        if not full_path.exists() or not full_path.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")

        # 检查文件是否在允许的目录内
        if not str(full_path).startswith(str(settings.output_dir)):
            raise HTTPException(status_code=403, detail="禁止访问此文件")

        media = "text/markdown"
        suffix = full_path.suffix.lower()
        if suffix in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            media = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }.get(suffix, "application/octet-stream")

        return FileResponse(
            path=full_path,
            filename=full_path.name,
            media_type=media
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件下载错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/file-content/{file_path:path}")
async def get_file_content(file_path: str):
    """获取文件内容（用于预览）"""
    try:
        # 安全检查
        settings = get_settings()
        full_path = Path(file_path)

        if not full_path.exists() or not full_path.is_file():
            raise HTTPException(status_code=404, detail="文件不存在")

        if not str(full_path).startswith(str(settings.output_dir)):
            raise HTTPException(status_code=403, detail="禁止访问此文件")

        # 图片/音视频：直接返回静态地址，避免旧「预览」按钮当文本打开报错
        if full_path.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp", ".gif"}:
            url = _to_outputs_url(full_path)
            return JSONResponse(content={
                "filename": full_path.name,
                "content": f"![预览]({url})\n\n图片地址：{url}\n（请打开 /gallery 看大图）",
                "url": url,
                "is_image": True,
                "size": full_path.stat().st_size,
            })
        if full_path.suffix.lower() in {".mp3", ".mp4", ".webm"}:
            raise HTTPException(
                status_code=400,
                detail="该文件是音视频，请用下载查看，不能按文本打开"
            )

        with open(full_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return JSONResponse(content={
            "filename": full_path.name,
            "content": content,
            "size": len(content)
        })

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"文件读取错误: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/score")
async def score_note(request: ScoreRequest):
    """对已有文案做网感打分（无需训练模型）"""
    try:
        from video_note_generator.xhs_scorer import XiaohongshuScorer
        scorer = XiaohongshuScorer()
        result = scorer.score(request.title, request.body, request.category)
        return result.to_dict()
    except Exception as e:
        logger.error(f"打分失败: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/templates")
async def list_templates():
    """返回完整品类模板（结构、范文、爆款示例）——给前端盖房子用，不是空壳"""
    try:
        from video_note_generator.xhs_scorer import load_templates
        data = load_templates()
        cats = []
        for c in data.get("categories", []):
            cid = c.get("id") or ""
            cats.append({
                "id": cid,
                "name": c.get("name"),
                "tone": c.get("tone"),
                "hook_styles": c.get("hook_styles", []),
                "structure": c.get("structure", []),
                "structure_detail": c.get("structure_detail", []),
                "few_shot_title": c.get("few_shot_title", ""),
                "few_shot_body": c.get("few_shot_body", ""),
                "viral_examples": c.get("viral_examples", []),
                "cover_hint": c.get("cover_hint", ""),
                "cover_image": f"/static/images/templates/{cid}.jpg" if cid else "",
                "cover_thumb": f"/static/images/templates/{cid}_thumb.jpg" if cid else "",
            })
        return {"categories": cats}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/latest-images")
async def latest_images():
    """返回最近一次生成的配图，便于验证预览（无需重新跑视频）"""
    try:
        settings = get_settings()
        img_root = Path(settings.output_dir) / "images"
        if not img_root.exists():
            return {"images": [], "urls": [], "message": "还没有配图"}

        dirs = [d for d in img_root.iterdir() if d.is_dir() and d.name != "_demo"]
        if not dirs:
            dirs = [d for d in img_root.iterdir() if d.is_dir()]
        if not dirs:
            return {"images": [], "urls": [], "message": "还没有配图目录"}

        latest = max(dirs, key=lambda p: p.stat().st_mtime)
        # 真实截帧是 jpg；旧文字卡片是 png —— 两种都要扫
        files = []
        for pattern in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
            files.extend(latest.glob(pattern))
        files = sorted(
            set(files),
            key=lambda p: (
                0 if "cover" in p.name.lower() or p.name.lower().startswith("frame_01") else 1,
                p.name,
            ),
        )
        images = [str(p).replace("\\", "/") for p in files]
        urls = [_to_outputs_url(p) for p in files]
        return {
            "images": urls,  # 前端直接当 img.src 用
            "paths": images,
            "urls": urls,
            "folder": latest.name,
            "message": f"已加载 {len(urls)} 张配图（{latest.name}）",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/gallery", response_class=HTMLResponse)
async def gallery_page():
    """零 JS 依赖的配图画廊：浏览器打开就能直接看图"""
    settings = get_settings()
    img_root = Path(settings.output_dir) / "images"
    dirs = []
    if img_root.exists():
        dirs = [d for d in img_root.iterdir() if d.is_dir() and d.name != "_demo"] or [
            d for d in img_root.iterdir() if d.is_dir()
        ]
    if not dirs:
        return HTMLResponse("<h1>还没有配图</h1><p><a href='/'>回首页</a></p>")

    latest = max(dirs, key=lambda p: p.stat().st_mtime)
    files = []
    for pattern in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
        files.extend(latest.glob(pattern))
    files = sorted(set(files), key=lambda p: p.name)
    imgs = "".join(
        f'<figure style="margin:0 0 24px">'
        f'<img src="{_to_outputs_url(p)}?t={int(p.stat().st_mtime)}" '
        f'style="max-width:100%;height:auto;border-radius:12px;display:block" alt="{p.name}">'
        f'<figcaption style="color:#64748b;margin-top:8px">{p.name}</figcaption></figure>'
        for p in files
    )
    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>红笔配图画廊 · {latest.name}</title>
<style>
body{{font-family:system-ui,sans-serif;max-width:720px;margin:40px auto;padding:0 16px;background:#f8fafc;color:#0f172a}}
a{{color:#1777FF}}
</style></head><body>
<h1>配图画廊</h1>
<p>目录 <code>{latest.name}</code> · 共 {len(files)} 张 · <a href="/">回创作台</a></p>
{imgs or "<p>此目录没有图片文件</p>"}
</body></html>"""
    return HTMLResponse(html)


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "ok", "product": "红笔", "timestamp": datetime.now().isoformat()}


# ========== 启动事件 ==========

@app.on_event("startup")
async def startup_event():
    """应用启动时的初始化"""
    import os
    import shutil

    logger.info("=" * 60)
    logger.info("红笔 Hongbi 正在启动...")
    logger.info("=" * 60)

    # 注入本地 FFmpeg 到 PATH，供 yt-dlp / whisper 使用
    try:
        settings = Settings()
        ffmpeg_candidates = []
        if settings.ffmpeg_path:
            ffmpeg_candidates.append(Path(settings.ffmpeg_path))
        ffmpeg_candidates.append(Path(__file__).parent / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe")
        for cand in ffmpeg_candidates:
            if cand.exists():
                bin_dir = str(cand.parent)
                os.environ["PATH"] = bin_dir + os.pathsep + os.environ.get("PATH", "")
                os.environ["FFMPEG_BINARY"] = str(cand)
                logger.info(f"已加载 FFmpeg: {cand}")
                break
        else:
            if not shutil.which("ffmpeg"):
                logger.warning("未找到 FFmpeg，Whisper 转写可能失败")
    except Exception as e:
        logger.warning(f"FFmpeg 检测失败: {e}")

    # Cookie 自动导出可能弹窗阻塞，启动时仅检测、不强制导出
    try:
        settings = Settings()
        cookie_file = settings.cookie_file or "cookies.txt"
        cookie_manager = CookieManager(cookie_file=cookie_file, logger=logger)
        logger.info("检查 Cookies 配置...")
        if cookie_manager.has_cookies():
            logger.info(f"已有 cookies 文件：{cookie_file}")
        else:
            logger.warning("未找到 cookies 文件（部分平台下载可能失败）")
            logger.warning("需要时请手动运行: python export_cookies.py")
    except Exception as e:
        logger.error(f"Cookies 检查失败：{e}")
        logger.warning("程序将继续运行")

    logger.info("=" * 60)
    logger.info("应用启动完成！")
    logger.info("访问: http://localhost:8001")
    logger.info("=" * 60)


# ========== 启动配置 ==========

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "web_app:app",
        host="0.0.0.0",
        port=8001,
        reload=False,
        log_level="info"
    )
