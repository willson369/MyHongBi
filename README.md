# 红笔 Hongbi

> 视频一键变小红书爆款，**网感分看得见**。

基于开源项目 [whotto/Video_note_generator](https://github.com/whotto/Video_note_generator) V2 增强：保留视频下载 / 转写 / AI 生成管线，增加品类模板、规则网感打分、去 AI 味改写与付费向产品界面。

## 和「只会转写」有什么不同

| 能力 | 普通工具 | 红笔 |
|------|----------|------|
| 视频转文字 | ✅ | ✅ |
| 小红书排版 | ✅ | ✅ |
| 品类爆款结构模板 | ❌ | ✅ 干货 / 情绪 / 种草 |
| 网感分 0-100 | ❌ | ✅ 规则清单，无需训练 |
| 低分自动去 AI 味改写 | ❌ | ✅ |
| 粘贴自己的爆款参考 | ❌ | ✅ |

说明：网感分不是平台真实算法，而是可解释的创作清单评分，适合独立开发者快速落地。

## 快速开始

### 1. 环境

- Python 3.8+
- FFmpeg（加入 PATH，或在 `.env` 里配置 `FFMPEG_PATH`）
- OpenRouter API Key

### 2. 安装

```bash
cd F:\hongbi
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 配置

编辑 `.env`，把占位 Key 换成你的：

```ini
OPENROUTER_API_KEY=sk-or-v1-你的真实密钥
AI_MODEL=google/gemini-2.0-flash-exp:free
```

### 4. 启动

```bash
python web_app.py
```

浏览器打开：http://localhost:8001

## 使用方式

1. 粘贴视频链接  
2. 选择品类（干货知识 / 情绪共鸣 / 种草带货）  
3. 可选：粘贴你自己的爆款笔记作风格参考  
4. 生成后查看网感分、备选标题、正文，复制或下载  

## 项目结构（关键增强）

```
data/xhs_templates.json          # 品类模板库
src/video_note_generator/
  xhs_scorer.py                  # 网感规则打分
  generators/xiaohongshu.py      # 模板注入 + 低分改写
templates/index.html             # 鱼皮风产品界面
static/css/style.css
static/js/app.js
```

上游完整代码仍保留在 `_upstream/`（仅作对照，不参与运行）。

## 许可与致谢

- 本产品增强层代码可按你的需要继续修改
- 上游项目遵循其 MIT License
- 感谢 Video_note_generator / Whisper / yt-dlp / OpenRouter
