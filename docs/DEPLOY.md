# 部署说明（MyHongBi / 红笔）

仓库：https://github.com/willson369/MyHongBi  
本地路径：`D:\hongbi\hongbi`

## 技术栈摘要

- FastAPI + Uvicorn（`web_app.py`，默认端口 `8001`）
- 本地 **FFmpeg**（抽音频/抽帧）
- **OpenAI Whisper**（本地模型，体积大、CPU/内存要求高、任务可跑数分钟）
- yt-dlp / 视频下载、OpenRouter API、静态前端（`templates/` + `static/`）

## 已选方案：(b) 整站 Docker

**不适合**把完整流水线部署到纯 Vercel Serverless。已采用 **Railway / Render / Fly / VPS** 容器部署。

| 能力 | Vercel Serverless / Edge | 本项目需求 |
|------|--------------------------|------------|
| 长任务（Whisper / 下载 / ffmpeg） | 超时短 | 常需数分钟 |
| 本地 ffmpeg / Whisper 模型 | 无持久系统包 | 必需 |
| 大依赖与模型缓存 | 体积与冷启动限制 | `whisper` + 模型数百 MB+ |

### 平台优先级

1. **Railway**（首选）— `Dockerfile` 构建，环境变量注入 secrets  
2. **Render** — Web Service + Docker，若 Railway 不可用  
3. **Fly.io / 自建 VPS** — 备选；本地可用 `docker compose up -d`

无自定义域名：使用平台默认域名（如 `*.up.railway.app` / `*.onrender.com`）。

## 已准备文件

- `Dockerfile` — 系统 `ffmpeg` + Python 依赖，监听 `$PORT`  
- `docker-compose.yml` — 本地/VPS：端口 8001，挂载 notes/cache/logs，`env_file: .env`  
- `.dockerignore` — 排除 `venv`、`.env`、本地 `tools/`  

## 环境变量（名称列表；勿把真实值写入仓库）

见 `.env.example`。线上至少设置：

| 名称 | 说明 |
|------|------|
| `OPENROUTER_API_KEY` | 必需 |
| `OPENROUTER_API_URL` | 建议 |
| `OPENROUTER_APP_NAME` | 建议 |
| `OPENROUTER_HTTP_REFERER` | 建议 |
| `AI_MODEL` / `VISION_MODEL` / `WHISPER_MODEL` | 模型 |
| `FFMPEG_PATH` | 容器内设为 `/usr/bin/ffmpeg` |
| `OUTPUT_DIR` / `CACHE_DIR` / `LOG_DIR` | 容器内路径 |
| `PORT` | 平台通常自动注入；本地默认 `8001` |

可选：`UNSPLASH_ACCESS_KEY`、`UNSPLASH_SECRET_KEY`，以及 `MAX_TOKENS`、`TEMPERATURE` 等生成参数。

**切勿提交 `.env`。** Secrets 只通过平台 Environment Variables 注入。

## 本地 Docker / Compose

```bash
# 需本机已安装 Docker
cd D:\hongbi\hongbi
docker compose config   # 校验语法
docker compose up -d --build
curl http://127.0.0.1:8001/health
```

## 本地非 Docker 启动

```bat
D:\hongbi\hongbi\start_hongbi.bat
```

健康检查：`GET /health`

## Railway 快速部署

```bash
npm i -g @railway/cli
railway login
railway init
railway up
# 将本地 .env 中的键注入为变量（不要在终端打印值）
railway variables set FFMPEG_PATH=/usr/bin/ffmpeg OUTPUT_DIR=/app/generated_notes CACHE_DIR=/app/.cache LOG_DIR=/app/logs
```

生成公开 URL 后访问：`https://<your-service>.up.railway.app/health`

## Render / Fly / VPS 备选

- **Render**：New → Web Service → 连接 GitHub 仓库 → Docker Runtime → 设置上述环境变量 → Deploy  
- **Fly.io**：`fly launch` + `fly secrets set`（需 `flyctl`）  
- **VPS**：`docker compose up -d`，反向代理到 `8001`

## 注意

- Whisper 首次运行会下载模型，需足够磁盘与内存（建议 ≥2GB RAM；medium 模型更大）。  
- 平台可能按用量计费；部署前确认账号额度。  
