@echo off
cd /d D:\hongbi\hongbi
set PYTHONPATH=D:\hongbi\hongbi\src
set PATH=D:\hongbi\hongbi\tools\ffmpeg\bin;%PATH%
call venv\Scripts\activate.bat
echo Starting Hongbi at http://127.0.0.1:8001
python -c "import uvicorn; uvicorn.run('web_app:app', host='127.0.0.1', port=8001, reload=False)"
pause
