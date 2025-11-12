@echo off
REM ==========================================================
REM 🧠 Re-embed all risk summaries into FAISS for RAG search
REM ==========================================================

REM Go to project root
cd /d "%~dp0\.."

REM Create logs directory if it doesn't exist
if not exist "logs" mkdir logs

set timestamp=%date:~-4,4%%date:~4,2%%date:~7,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set timestamp=%timestamp: =0%
set log_file=logs\reembed_risk_%timestamp%.log

echo 🧠 [%date% %time%] Starting daily risk re-embedding... > %log_file%

REM Activate virtual environment if needed
call .venv\Scripts\activate.bat

REM Run the embedding job and append output to log
python -m scripts.reembed_risk_summaries --apply >> %log_file% 2>&1

echo ✅ [%date% %time%] Risk re-embedding completed. >> %log_file%
echo Logs saved to %log_file%

REM Optional pause for manual runs
REM pause
