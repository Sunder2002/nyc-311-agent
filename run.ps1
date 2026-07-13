Write-Host "==========================================" -ForegroundColor Cyan
Write-Host "  Starting NYC 311 Data Agent (DeepSeek)  " -ForegroundColor Cyan
Write-Host "==========================================" -ForegroundColor Cyan
Write-Host ""

Write-Host "[1/3] Activating Virtual Environment..." -ForegroundColor Green
.\venv\Scripts\Activate.ps1

Write-Host "[2/3] Configuring Streamlit for Production..." -ForegroundColor Green
$env:STREAMLIT_CLIENT_TOOLBAR_MODE = "viewer"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"

Write-Host "[3/3] Booting Enterprise Streamlit Server..." -ForegroundColor Green
python -m streamlit run src\app.py --server.fileWatcherType none
