# Локальный запуск без Docker (Windows PowerShell).
#   .\run_local.ps1              — поднять приложение на http://localhost:8000
#   .\run_local.ps1 -Port 8080   — другой порт
#   .\run_local.ps1 -Rebuild     — пересобрать базу из XLSX с нуля
#   .\run_local.ps1 -Install     — доустановить зависимости (нужно один раз)

param([switch]$Rebuild, [switch]$Install, [int]$Port = 8000)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$db = Join-Path $root "data\bvi_database.db"

# python из Microsoft Store — заглушка, поэтому предпочитаем лаунчер py
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" }
      elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" }
      else { throw "Python не найден. Установите его с python.org и повторите." }

Set-Location (Join-Path $root "backend")

if ($Install) {
    Write-Host "Ставлю зависимости..." -ForegroundColor Cyan
    & $py -m pip install -r requirements.txt
}

if ($Rebuild -and (Test-Path $db)) { Remove-Item $db -Force }
if (-not (Test-Path $db)) {
    Write-Host "Собираю базу из XLSX (около 30 секунд)..." -ForegroundColor Cyan
    & $py ingest_data.py
}

Write-Host ""
Write-Host "Приложение: http://localhost:$Port" -ForegroundColor Green
Write-Host "Swagger:    http://localhost:$Port/docs"
Write-Host "Остановить: Ctrl+C"
Write-Host ""
& $py -m uvicorn main:app --host 0.0.0.0 --port $Port
