@echo off
echo ==========================================
echo   Starting NYC 311 Data Agent (DeepSeek)
echo ==========================================
echo.

echo [1/2] Activating Virtual Environment...
call venv\Scripts\activate.bat

echo [2/2] Booting Enterprise Streamlit Server...
python -m streamlit run src\app.py
