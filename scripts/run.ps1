$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
cd $ProjectRoot\..\src
& "..\venv\Scripts\python.exe" -m streamlit run app.py
