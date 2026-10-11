@echo off
title Swing Trader India
cd /d "C:\Users\acer\Downloads\files (6)\swing-trader-india"
".venv\Scripts\python.exe" -m streamlit run "src\swingtrader\ui\app.py" --server.address 127.0.0.1 --server.port 8501 --server.headless true --browser.gatherUsageStats false
pause
