$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "Starting Alleycat Router server..." -ForegroundColor Cyan
Write-Host ""

if (Test-Path ".\.venv\Scripts\python.exe") {
    $python = ".\.venv\Scripts\python.exe"
} else {
    $python = "python"
}

& $python -m pip install -r requirements.txt

Write-Host ""
Write-Host "Server will run at:" -ForegroundColor Green
Write-Host "http://127.0.0.1:8000"
Write-Host ""
Write-Host "API docs:" -ForegroundColor Green
Write-Host "http://127.0.0.1:8000/docs"
Write-Host ""

& $python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000