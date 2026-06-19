#Requires -Version 5.1
<#
.SYNOPSIS
    Knowledge Graph Engine - one-command dev startup for Windows.

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

# --- Colour helpers ---
function Write-Step  { param($msg) Write-Host "`n >> $msg" -ForegroundColor Cyan }
function Write-OK    { param($msg) Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "    !!  $msg" -ForegroundColor Yellow }
function Write-Fatal { param($msg) Write-Host "`n FAIL  $msg" -ForegroundColor Red; exit 1 }

# --- Stop mode ---
if ($Stop) {
    Write-Step "Stopping Docker infra..."
    docker compose -f "$Root\docker-compose.yml" stop neo4j postgres redis
    Write-Step "Killing backend / worker / frontend processes..."
    Get-Process -Name "python", "uvicorn", "node" -ErrorAction SilentlyContinue |
        Stop-Process -Force -ErrorAction SilentlyContinue
    Write-OK "Done."
    exit 0
}

# --- Prerequisite checks ---
Write-Step "Checking prerequisites..."

foreach ($cmd in @("python", "node", "docker")) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Fatal "$cmd not found in PATH. Please install it and re-run."
    }
}

# Check Docker is running (avoid 2>&1 which causes NativeCommandError in PS 5.1)
$null = docker info
if ($LASTEXITCODE -ne 0) {
    Write-Fatal "Docker is not running. Start Docker Desktop and re-run."
}

# Detect pnpm vs npm (prefer pnpm when pnpm-lock.yaml is present)
$pm = "npm"
if ((Get-Command pnpm -ErrorAction SilentlyContinue) -and (Test-Path "$Root\frontend\pnpm-lock.yaml")) {
    $pm = "pnpm"
}
Write-OK "python, node, docker, package manager ($pm) - all present."

# --- .env setup ---
Write-Step "Checking environment file..."
if (-not (Test-Path "$Root\.env")) {
    Copy-Item "$Root\.env.example" "$Root\.env"
    Write-Warn ".env created from .env.example"
    Write-Warn "Add your GEMINI_API_KEY to .env before queries will work."
} else {
    $envContent = Get-Content "$Root\.env" -Raw
    $keyMatch   = [regex]::Match($envContent, 'GEMINI_API_KEY=(.+)')
    $key        = $keyMatch.Groups[1].Value.Trim()
    if (-not $key -or $key -eq "") {
        Write-Warn "GEMINI_API_KEY is not set in .env - queries will fail until you add it."
    } else {
        Write-OK ".env present with API key."
    }
}

# --- Python virtual environment ---
Write-Step "Setting up Python virtual environment..."
$venvPython = "$Root\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "    Creating .venv..."
    python -m venv "$Root\.venv"
}
Write-OK ".venv ready."

# --- Python dependencies ---
Write-Step "Installing/updating Python dependencies..."
& "$Root\.venv\Scripts\pip.exe" install -r "$Root\requirements.txt" --quiet --upgrade
Write-OK "Python deps up to date."

# --- Frontend dependencies ---
Write-Step "Installing/updating frontend dependencies (using $pm)..."
Push-Location "$Root\frontend"
if ($pm -eq "pnpm") {
    pnpm install --frozen-lockfile
} else {
    npm install
}
Pop-Location
Write-OK "Node deps up to date."

# --- Docker infra ---
Write-Step "Starting Docker infrastructure (Neo4j, Postgres, Redis)..."
docker compose -f "$Root\docker-compose.yml" up -d neo4j postgres redis
if ($LASTEXITCODE -ne 0) { Write-Fatal "docker compose up failed." }

# Wait for services to be healthy
Write-Host "    Waiting for services to be healthy..." -NoNewline
$timeout    = 120
$elapsed    = 0
$interval   = 5
$allHealthy = $false

do {
    Start-Sleep -Seconds $interval
    $elapsed += $interval

    # Try JSON health query (docker compose v2+)
    $psJson = docker compose -f "$Root\docker-compose.yml" ps --format json 2>$null
    if ($psJson) {
        try {
            $services   = ($psJson | ConvertFrom-Json) | Where-Object { $_ -ne $null }
            $targets    = $services | Where-Object { $_.Service -in @("neo4j", "postgres", "redis") }
            $notHealthy = $targets   | Where-Object { $_.Health -ne "healthy" }
            $allHealthy = ($notHealthy | Measure-Object).Count -eq 0 `
                       -and ($targets  | Measure-Object).Count -eq 3
        } catch {
            $allHealthy = $false
        }
    }

    # Fallback: verify ports are reachable
    if (-not $allHealthy) {
        $neo4jOk    = (Test-NetConnection 127.0.0.1 -Port 7474 -WarningAction SilentlyContinue).TcpTestSucceeded
        $postgresOk = (Test-NetConnection 127.0.0.1 -Port 5432 -WarningAction SilentlyContinue).TcpTestSucceeded
        $redisOk    = (Test-NetConnection 127.0.0.1 -Port 6379 -WarningAction SilentlyContinue).TcpTestSucceeded
        $allHealthy = $neo4jOk -and $postgresOk -and $redisOk
    }

    Write-Host "." -NoNewline
} while (-not $allHealthy -and $elapsed -lt $timeout)

if (-not $allHealthy) {
    Write-Host ""
    Write-Warn "Services not fully ready after ${timeout}s - continuing anyway."
    Write-Warn "Run: docker compose ps   to check status."
} else {
    Write-Host " ready!" -ForegroundColor Green
}

# --- Launch terminal windows ---
# Uses base64-encoded commands (-EncodedCommand) to avoid quoting problems with
# complex PowerShell strings across both Windows Terminal and plain PS windows.

$useWT = [bool](Get-Command wt -ErrorAction SilentlyContinue)

function Start-DevProcess {
    param(
        [string]$Title,
        [string]$Command
    )
    $bytes   = [System.Text.Encoding]::Unicode.GetBytes($Command)
    $encoded = [Convert]::ToBase64String($bytes)

    if ($useWT) {
        Start-Process wt -ArgumentList @(
            "new-tab", "--title", $Title,
            "--", "powershell.exe", "-NoExit", "-EncodedCommand", $encoded
        )
    } else {
        Start-Process powershell -ArgumentList @(
            "-NoExit", "-EncodedCommand", $encoded
        ) -WindowStyle Normal
    }
}

$activateVenv = ". '$Root\.venv\Scripts\Activate.ps1'"

# Backend (FastAPI)
Write-Step "Starting backend (FastAPI on :8000)..."
$backendCmd = "$activateVenv; Set-Location '$Root'; python -m uvicorn backend.main:app --reload --host 127.0.0.1 --port 8000"
Start-DevProcess "kgre-backend" $backendCmd
Write-OK "Backend window launched."

# RQ ingestion worker
Write-Step "Starting RQ ingestion worker..."
$workerCmd = "$activateVenv; Set-Location '$Root'; python scripts/ingestion_worker.py"
Start-DevProcess "kgre-worker" $workerCmd
Write-OK "Worker window launched."

# Frontend (Vite)
Write-Step "Starting frontend (Vite on :5173)..."
$frontendCmd = "Set-Location '$Root\frontend'; $pm run dev"
Start-DevProcess "kgre-frontend" $frontendCmd
Write-OK "Frontend window launched."

# --- Summary ---
Write-Host ""
Write-Host "    ============================================================" -ForegroundColor Cyan
Write-Host "    Knowledge Graph Engine - dev environment starting up"        -ForegroundColor Cyan
Write-Host "    ============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "    Frontend   ->  http://localhost:5173" -ForegroundColor White
Write-Host "    Backend    ->  http://localhost:8000" -ForegroundColor White
Write-Host "    API docs   ->  http://localhost:8000/docs" -ForegroundColor White
Write-Host "    Health     ->  http://localhost:8000/health/ready" -ForegroundColor White
Write-Host "    Neo4j UI   ->  http://localhost:7474" -ForegroundColor White
Write-Host ""
Write-Host "    Stop everything:  .\dev.ps1 -Stop" -ForegroundColor DarkGray
Write-Host ""
