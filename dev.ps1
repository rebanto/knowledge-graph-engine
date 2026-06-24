#Requires -Version 5.1
<#
.SYNOPSIS
    Knowledge Graph Engine - one-command dev startup for Windows.

.DESCRIPTION
    Starts Docker infra and the three dev processes (backend, RQ worker,
    frontend) as fast as possible:
      * Docker infra boots first so Neo4j (the slow one) warms up while
        dependencies install in parallel.
      * Python / frontend dependencies are only (re)installed when their
        lockfile actually changes (hash-cached). Use -Force to override or
        -SkipDeps to skip entirely.
      * Stale processes on the dev ports are cleared before relaunch, so
        re-running never leaves a dead backend holding :8000.
      * The script only reports "ready" once the backend actually answers
        /health/live - not merely once the window is launched.

.USAGE
    From the project root in PowerShell:
        .\dev.ps1            # normal start (installs deps only if changed)
        .\dev.ps1 -SkipDeps  # fastest start, assume deps are current
        .\dev.ps1 -Force     # force a dependency reinstall
        .\dev.ps1 -Stop      # stop infra + dev processes
#>
param(
    [switch]$Stop,
    [switch]$SkipDeps,
    [switch]$Force
)

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot

# --- Colour helpers ---
function Write-Step  { param($msg) Write-Host "`n >> $msg" -ForegroundColor Cyan }
function Write-OK    { param($msg) Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Warn  { param($msg) Write-Host "    !!  $msg" -ForegroundColor Yellow }
function Write-Fatal { param($msg) Write-Host "`n FAIL  $msg" -ForegroundColor Red; exit 1 }

# --- Fast TCP port probe (replaces the slow Test-NetConnection) ---
function Test-Port {
    param([int]$Port, [string]$TargetHost = "127.0.0.1", [int]$TimeoutMs = 400)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $client.BeginConnect($TargetHost, $Port, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne($TimeoutMs)) {
            $client.EndConnect($iar)
            return $true
        }
        return $false
    } catch {
        return $false
    } finally {
        $client.Close()
    }
}

# --- Kill whatever is listening on a dev port (clean relaunch) ---
function Stop-Port {
    param([int]$Port)
    try {
        $conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop
        foreach ($c in $conns) {
            Stop-Process -Id $c.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch {
        # No listener on this port - nothing to do.
    }
}

# --- Kill the RQ worker (it has no port, so match it by command line) ---
function Stop-Worker {
    Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match 'ingestion_worker\.py' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

# --- Stop mode ---
if ($Stop) {
    Write-Step "Stopping dev processes (backend :8000, frontend :5173, worker)..."
    Stop-Port 8000
    Stop-Port 5173
    Stop-Worker
    Write-Step "Stopping Docker infra..."
    docker compose -f "$Root\docker-compose.yml" stop neo4j postgres redis chroma
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

# --- Start Docker infra FIRST so Neo4j boots while we install deps ---
# Neo4j is the slowest component to become healthy; kicking it off now lets its
# ~30-45s boot overlap with dependency installation instead of running serially.
Write-Step "Starting Docker infrastructure (Neo4j, Postgres, Redis, Chroma)..."
docker compose -f "$Root\docker-compose.yml" up -d neo4j postgres redis chroma
if ($LASTEXITCODE -ne 0) { Write-Fatal "docker compose up failed." }
Write-OK "Containers started (warming up in background)."

# --- Python virtual environment ---
Write-Step "Setting up Python virtual environment..."
$venvPython = "$Root\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "    Creating .venv..."
    python -m venv "$Root\.venv"
}
Write-OK ".venv ready."

# --- Dependency install (hash-cached - only runs when a lockfile changes) ---
$cacheDir = "$Root\.dev-cache"
if (-not (Test-Path $cacheDir)) { New-Item -ItemType Directory -Path $cacheDir | Out-Null }

function Install-IfChanged {
    param(
        [string]$Name,
        [string]$LockFile,
        [string]$MarkerName,
        [scriptblock]$Install
    )
    $marker = Join-Path $cacheDir $MarkerName
    $hash   = (Get-FileHash $LockFile -Algorithm SHA256).Hash
    $cached = if (Test-Path $marker) { (Get-Content $marker -Raw).Trim() } else { "" }

    if (-not $Force -and $cached -eq $hash) {
        Write-OK "$Name unchanged - skipping install."
        return
    }

    Write-Host "    Installing $Name dependencies..."
    & $Install
    if ($LASTEXITCODE -ne 0) { Write-Fatal "$Name dependency install failed." }
    Set-Content -Path $marker -Value $hash -Encoding ASCII
    Write-OK "$Name deps up to date."
}

if ($SkipDeps) {
    Write-Step "Skipping dependency install (-SkipDeps)."
} else {
    Write-Step "Checking Python dependencies..."
    Install-IfChanged -Name "Python" -LockFile "$Root\requirements.txt" -MarkerName "py-deps.hash" -Install {
        & "$Root\.venv\Scripts\pip.exe" install -r "$Root\requirements.txt" --quiet
    }

    Write-Step "Checking frontend dependencies (using $pm)..."
    $frontLock = if (Test-Path "$Root\frontend\pnpm-lock.yaml") { "$Root\frontend\pnpm-lock.yaml" }
                 elseif (Test-Path "$Root\frontend\package-lock.json") { "$Root\frontend\package-lock.json" }
                 else { "$Root\frontend\package.json" }
    Install-IfChanged -Name "Frontend" -LockFile $frontLock -MarkerName "node-deps.hash" -Install {
        Push-Location "$Root\frontend"
        try {
            if ($pm -eq "pnpm") { pnpm install --frozen-lockfile } else { npm install }
        } finally {
            Pop-Location
        }
    }
}

# --- Wait for Docker infra to be healthy (fast probe, no leading sleep) ---
Write-Host "    Waiting for Neo4j / Postgres / Redis / Chroma..." -NoNewline
$timeout    = 120
$elapsed    = 0
$interval   = 2
$allHealthy = $false

while (-not $allHealthy -and $elapsed -lt $timeout) {
    # Fast TCP probes - Neo4j HTTP (7474) is the last port to open, so once all
    # answer the infra is effectively up. The backend's /health/ready does
    # the authoritative dependency check later.
    $neo4jOk    = Test-Port 7474
    $postgresOk = Test-Port 5432
    $redisOk    = Test-Port 6379
    $chromaOk   = Test-Port 8001
    $allHealthy = $neo4jOk -and $postgresOk -and $redisOk -and $chromaOk

    if (-not $allHealthy) {
        Start-Sleep -Seconds $interval
        $elapsed += $interval
        Write-Host "." -NoNewline
    }
}

if (-not $allHealthy) {
    Write-Host ""
    Write-Warn "Infra not fully ready after ${timeout}s - continuing anyway."
    Write-Warn "Run: docker compose ps   to check status."
} else {
    Write-Host " ready!" -ForegroundColor Green
}

# --- Clear stale dev processes so a relaunch doesn't collide on ports ---
Write-Step "Clearing any previous dev processes..."
Stop-Port 8000
Stop-Port 5173
Stop-Worker
Write-OK "Ports 8000 / 5173 free."

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
# --reload-dir backend keeps the file-watcher off node_modules / .venv /
# chroma_data / uploads, which otherwise makes uvicorn slow to boot and pegs CPU.
Write-Step "Starting backend (FastAPI on :8000)..."
$backendCmd = "$activateVenv; Set-Location '$Root'; python -m uvicorn backend.main:app --reload --reload-dir backend --host 127.0.0.1 --port 8000"
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

# --- Wait until the backend actually answers before declaring ready ---
# The window is launched, but uvicorn still has to import the app and run the
# lifespan (DB connect, create_all, migrations). Polling /health/live here means
# "ready" is true - so the frontend won't show a connection error on first load.
Write-Host "    Waiting for backend to respond..." -NoNewline
$backendReady = $false
for ($i = 0; $i -lt 60; $i++) {
    if (Test-Port 8000) {
        try {
            $resp = Invoke-WebRequest "http://127.0.0.1:8000/health/live" -UseBasicParsing -TimeoutSec 2
            if ($resp.StatusCode -eq 200) { $backendReady = $true; break }
        } catch {
            # Not up yet - keep polling.
        }
    }
    Start-Sleep -Milliseconds 500
    Write-Host "." -NoNewline
}

if ($backendReady) {
    Write-Host " ready!" -ForegroundColor Green
} else {
    Write-Host ""
    Write-Warn "Backend did not respond within 30s - check the kgre-backend window."
}

# --- Summary ---
Write-Host ""
Write-Host "    ============================================================" -ForegroundColor Cyan
Write-Host "    Knowledge Graph Engine - dev environment ready"              -ForegroundColor Cyan
Write-Host "    ============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "    Frontend   ->  http://localhost:5173" -ForegroundColor White
Write-Host "    Backend    ->  http://localhost:8000" -ForegroundColor White
Write-Host "    API docs   ->  http://localhost:8000/docs" -ForegroundColor White
Write-Host "    Health     ->  http://localhost:8000/health/ready" -ForegroundColor White
Write-Host "    Neo4j UI   ->  http://localhost:7474" -ForegroundColor White
Write-Host ""
Write-Host "    Faster restart:   .\dev.ps1 -SkipDeps" -ForegroundColor DarkGray
Write-Host "    Stop everything:  .\dev.ps1 -Stop" -ForegroundColor DarkGray
Write-Host ""
