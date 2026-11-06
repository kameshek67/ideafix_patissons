# Локальный запуск для разработки (Windows PowerShell), если нет just.
#   .\run_local.ps1               — окружение в Docker, API (:8000) и сайт (:3000)
#   .\run_local.ps1 -Rebuild      — пересобрать базу из XLSX
#   .\run_local.ps1 -ApiPort 8010 — API на другом порту (если 8000 занят)
# Нужны Docker Desktop, Python 3.13+ и Node.js 22+. uv поставится сам, если его нет.

param([switch]$Rebuild, [int]$ApiPort = 8000, [int]$WebPort = 3000)

$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

$env:OLYMP_DATABASE_URL = "postgresql+psycopg://olymp:olymp@localhost:5432/olymp"
$env:OLYMP_REDIS_URL = "redis://localhost:6379/0"
$env:OLYMP_RABBITMQ_URL = "amqp://olymp:olymp@localhost:5672/"
$env:OLYMP_API_URL = "http://127.0.0.1:$ApiPort"
$env:PYTHONUTF8 = "1"

# python из Microsoft Store — заглушка, поэтому предпочитаем лаунчер py
$py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } else { "python" }
function Uv {
    if (Get-Command uv -ErrorAction SilentlyContinue) { & uv @args } else { & $py -m uv @args }
    if ($LASTEXITCODE) { throw "uv $args завершился с ошибкой" }
}
if (-not (Get-Command uv -ErrorAction SilentlyContinue)) {
    & $py -m uv --version *> $null
    if ($LASTEXITCODE) { Write-Host "Ставлю uv..." -ForegroundColor Cyan; & $py -m pip install --user uv }
}

Write-Host "Поднимаю PostgreSQL, Redis, RabbitMQ..." -ForegroundColor Cyan
docker compose -f infra/compose.yaml up -d --wait
if ($LASTEXITCODE) { throw "Docker не запустился: откройте Docker Desktop и повторите" }

Write-Host "Зависимости..." -ForegroundColor Cyan
Uv sync --all-packages
if (-not (Test-Path node_modules)) { npm install --no-audit --no-fund }

Write-Host "Миграции и база..." -ForegroundColor Cyan
Push-Location packages/db
Uv run alembic upgrade head
Pop-Location
if ($Rebuild) { Uv run olymp-ingest } else { Uv run olymp-ingest --if-empty }

Write-Host "API запускается в отдельном окне: http://localhost:$ApiPort/docs" -ForegroundColor Green
$uvCmd = if (Get-Command uv -ErrorAction SilentlyContinue) { "uv" } else { "$py -m uv" }
Start-Process powershell -ArgumentList "-NoExit", "-Command", "Set-Location '$root'; $uvCmd run uvicorn olymp_api.main:app --port $ApiPort"

Write-Host ""
Write-Host "Сайт: http://localhost:$WebPort   (остановить: Ctrl+C)" -ForegroundColor Green
Write-Host ""
npm run dev --workspace olymp-web -- -p $WebPort
