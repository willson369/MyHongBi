# Disk cleanup report (D:\hongbi\hongbi)

Date: 2026-08-06

## Before / after (project tree)

| Metric | Value |
|--------|-------|
| Before | ~1365 MB |
| After | ~927 MB |
| Freed in project | ~439 MB |
| Pip cache purged (user profile) | ~459 MB |
| **Total approx freed** | **~898 MB** |

## Removed (safe / regenerable)

| Item | Approx MB | Notes |
|------|-----------|-------|
| `tools/ffmpeg_extract/` | 191.6 | Duplicate of `tools/ffmpeg` |
| `tools/ffmpeg.zip` | 73 | Re-downloadable archive |
| `__pycache__/` (incl. under venv) | 170.7 | Regenerated on import |
| `generated_notes/` contents | 3.4 | Regenerable outputs |
| pip cache (`%LOCALAPPDATA%\pip\Cache`) | 459 | Outside repo |

## Kept

- Source code, `templates/`, `static/` (including new cover photos)
- `.env` (not committed)
- One working FFmpeg: `tools/ffmpeg/bin/ffmpeg.exe` (docs/ removed ~11 MB)
- `venv/` (~764 MB, mostly `torch` ~455 MB for Whisper) — needed for local run; recreate with `python -m venv venv && pip install -r requirements.txt` if deleted
- Whisper model cache at `%USERPROFILE%\.cache\whisper` (~138 MB) — kept so transcription still works offline

## Follow-up cleanup (2026-08-06)

- Removed `tools/ffmpeg/doc/`, `_upstream/`, regenerated `__pycache__`
- Project tree ≈ **961 MB** (not ~30 GB)
- D: drive large folders are mostly unrelated (games / BaiduNetdisk / WeChat). `D:\hongbi` itself is ~1 GB.
- If you only use Railway online, you can delete local `venv/` + `tools/ffmpeg/` (~950 MB) and reinstall later when needed.

## Path fixes

- `start_hongbi.bat` updated from `F:\hongbi` → `D:\hongbi\hongbi`

## .gitignore

Already ignored: `venv/`, `.env`, `generated_notes/`, `tools/ffmpeg/`, `tools/ffmpeg_extract/`, `tools/ffmpeg*.zip`. Added notes for zip/extract/doc helpers.
