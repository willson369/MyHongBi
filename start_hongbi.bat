@echo off
cd /d F:\hongbi
set PYTHONPATH=F:\hongbi\src
set PATH=F:\hongbi\tools\ffmpeg\bin;%PATH%
call venv\Scripts\activate.bat
echo Starting Hongbi at http://127.0.0.1:8001
python -c "import uvicorn; uvicorn.run('web_app:app', host='127.0.0.1', port=8001, reload=False)"
pause
