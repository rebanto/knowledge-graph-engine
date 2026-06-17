#Requires -Version 5.1
<#
.SYNOPSIS
    Knowledge Graph Engine — one-command dev startup for Windows.

.DESCRIPTION
    Installs/updates all dependencies, starts Docker infra, then opens
    three terminal windows: backend (FastAPI), worker (RQ), and frontend (Vite).

.USAGE
    From the project root in PowerShell:
        .\dev.ps1

    Stop everything:
        .\dev.ps1 -Stop
#>
param(
    [switch]$Stop
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

# ── Colour helpers ─────────────────────────────────────────────────────────────
function Write-Step  { param($msg) Write-Host "`n▶  $msg" -ForegroundColor Cyan }
function Write-OK    { param($msg) Write-Host "   ✓  $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "   ⚠  $msg" -ForegroundColor Yellow }
function Write-Fatal { param($msg) Write-Host "`n✗  $msg" -ForegroundColor Red; exit 1 }

# ── Stop mode ─────────────────────────────────────────────────────────────────
if ($Stop) {
    Write-Step "Stopping Docker infra..."
    docker compose -f "$Root\docker-compose.yml" stop neo4j postgres redis
    Write-Step "Killing backend / worker / frontend processes..."
    Get-Process -Name "python", "uvicorn", "node" -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -match "kgre|Knowledge Graph" } |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Write-OK "Done."
    exit 0
}

# ── Prerequisite checks ────────────────────────────────────────────────────────
Write-Step "Checking prerequisites..."

foreach ($cmd in @("python", "node", "npm", "docker")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Fatal "$cmd not found in PATH. Please install it and re-run."
    }
}

$dockerRunning = docker info 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Fatal "Docker is not running. Start Docker Desktop and re-run."
}
Write-OK "python, node, npm, docker — all present."

# ── .env setup ────────────────────────────────────────────────────────────────
Write-Step "Checking environment file..."
if (-not (Test-Path "$Root\.env")) {
    Copy-Item "$Root\.env.example" "$Root\.env"
    Write-Warn ".env created from .env.example"
    Write-Warn "Add your GEMINI_API_KEY to .env before queries will work."
} else {
    $key = (Get-Content "$Root\.env" | Select-String "GEMINI_API_KEY=(.+)").Matches.Groups[1].Value
    if (-not $key -or $key.Trim() -eq "") {
        Write-Warn "GEMINI_API_KEY is not set in .env — queries will fail until you add it."
    } else {
        Write-OK ".env present with API key."
    }
}

# ── Python virtual environment ─────────────────────────────────────────────────
Write-Step "Setting up Python virtual environment..."
$venvPython = "$Root\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "   Creating .venv..."
    python -m venv "$Root\.venv"
}
Write-OK ".venv ready."

# ── Python dependencies ────────────────────────────────────────────────────────
Write-Step "Installing/updating Python dependencies..."
& "$Root\.venv\Scripts\pip.exe" install -r "$Root\requirements.txt" --quiet --upgrade
Write-OK "Python deps up to date."

# ── Frontend dependencies ──────────────────────────────────────────────────────
Write-Step "Installing/updating frontend dependencies..."
Push-Location "$Root\frontend"
npm install --silent
Pop-Location
Write-OK "Node deps up to date."

# ── Docker infra ───────────────────────────────────────────────────────────────
Write-Step "Starting Docker infrastructure (Neo4j, Postgres, Redis)..."
docker compose -f "$Root\docker-compose.yml" up -d neo4j postgres redis
if ($LASTEXITCODE -ne 0) { Write-Fatal "docker compose up failed." }

# Wait for all three to be healthy
Write-Host "   Waiting for services to be healthy..." -NoNewline
$timeout  = 90   # seconds
$elapsed  = 0
$interval = 4
do {
    Start-Sleep -Seconds $interval
    $elapsed += $interval
    $ps = docker compose -f "$Root\docker-compose.yml" ps --format "{{.Service}}\t{{.Health}}" 2>$null
    $allHealthy = ($ps -split "`n" |
        Where-Object { $_ -match "^(neo4j|postgres|redis)" } |
        Where-Object { $_ -notmatch "healthy" }).Count -eq 0
    Write-Host "." -NoNewline
} while (-not $allHealthy -and $elapsed -lt $timeout)

if (-not $allHealthy) {
    Write-Host ""
    Write-Warn "Services not fully healthy after ${timeout}s — continuing anyway."
    Write-Warn "Run: docker compose ps   to check status."
} else {
    Write-Host " ready!" -ForegroundColor Green
}

# ── Launch terminals ───────────────────────────────────────────────────────────
# Prefer Windows Terminal (wt) for nicer tabs; fall back to plain PowerShell windows.
$useWT = [bool](Get-Command wt -ErrorAction SilentlyContinue)

function Start-DevProcess {
    param($Title, $Command)
    if ($useWT) {
        Start-Process wt -ArgumentList "new-tab", "--title", $Title,
            "powershell.exe", "-NoExit", "-Command", $Command
    } else {
        Start-Process powershell -ArgumentList "-NoExit", "-Command", $Command `
            -WindowStyle Normal
    }
}

$activateVenv = ". '$Root\.venv\Scripts\Activate.ps1'"

# Backend
Write-Step "Starting backend (FastAPI on :8000)..."
$backendCmd = "$activateVenv; cd '$Root'; uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000"
Start-DevProcess "kgre-backend" $backendCmd
Write-OK "Backend window launched."

# RQ worker
Write-Step "Starting RQ ingestion worker..."
$workerCmd  = "$activateVenv; cd '$Root'; rq worker ingestion ingestion_bulk"
Start-DevProcess "kgre-worker" $workerCmd
Write-OK "Worker window launched."

# Frontend
Write-Step "Starting frontend (Vite on :5173)..."
$frontendCmd = "cd '$Root\frontend'; npm run dev"
Start-DevProcess "kgre-frontend" $frontendCmd
Write-OK "Frontend window launched."

# ── Summary ────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "  Knowledge Graph Engine — dev environment running" -ForegroundColor Cyan
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Frontend   →  http://localhost:5173" -ForegroundColor White
Write-Host "  Backend    →  http://localhost:8000" -ForegroundColor White
Write-Host "  API docs   →  http://localhost:8000/docs" -ForegroundColor White
Write-Host "  Health     →  http://localhost:8000/health/ready" -ForegroundColor White
Write-Host "  Metrics    →  http://localhost:8000/metrics" -ForegroundColor White
Write-Host "  Neo4j UI   →  http://localhost:7474" -ForegroundColor White
Write-Host ""
Write-Host "  Stop everything:  .\dev.ps1 -Stop" -ForegroundColor DarkGray
Write-Host ""
