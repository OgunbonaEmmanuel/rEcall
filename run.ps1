$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    if (-not (Test-Path '.venv/Scripts/python.exe')) { throw 'Run the setup commands in README.md first.' }
    if (-not (Test-Path 'dist/index.html')) { throw 'Run npm run build first.' }
    Write-Host 'Recall: http://127.0.0.1:8765 (Ctrl+C to stop)'
    & '.venv/Scripts/python.exe' -m uvicorn backend.app:app --host 127.0.0.1 --port 8765
} finally {
    Pop-Location
}
