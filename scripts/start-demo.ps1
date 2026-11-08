<#
  One command to bring up the laptop side of the demo.

    .\scripts\start-demo.ps1 -Simulated               # simulated cane on this laptop (no hardware needed)
    .\scripts\start-demo.ps1 -CaneUrl http://192.168.43.50:8765   # REAL cane (Pi started with --lan) -> live patient
    .\scripts\start-demo.ps1 -Simulated -Local        # no internet: local database instead of Tiger Cloud
    .\scripts\start-demo.ps1 -Simulated -NoExpo       # everything except the Expo server (for checks)

  It: checks Docker and .env, starts the API, waits until it is healthy, loads the demo data,
  registers the simulated cane, starts the cane simulator, prints the addresses, then starts Expo
  with those addresses already filled in (so the app opens in live mode, nothing to type).
  Stop everything with:  .\scripts\stop-demo.ps1
#>
param(
  [switch]$Simulated,
  [string]$CaneUrl = "",
  [string]$CaneDeviceId = "cane-dev",   # the real cane's device_id (its /info shows it); firmware default is cane-dev
  [switch]$Local,
  [switch]$NoExpo
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
function Step($m) { Write-Host "==> $m" -ForegroundColor Cyan }
function Warn($m) { Write-Host "!!  $m" -ForegroundColor Yellow }
function Fail($m) { Write-Host "XX  $m" -ForegroundColor Red; exit 1 }

Step "Checking Docker"
docker info *> $null
if ($LASTEXITCODE -ne 0) { Fail "Docker is not running. Open Docker Desktop, wait for it to finish starting, and run this again." }

if (-not (Test-Path ".env")) { Fail "No .env file. Run: Copy-Item .env.example .env   then set JWT_SECRET (see docs/DEPLOY.md)." }

Step "Finding this laptop's address on the current network"
$cfg = Get-NetIPConfiguration | Where-Object { $_.IPv4DefaultGateway -ne $null -and $_.NetAdapter.Status -eq "Up" } | Select-Object -First 1
if (-not $cfg) { Fail "No network connection. Join the phone hotspot first." }
$ip = $cfg.IPv4Address.IPAddress
Write-Host "    $ip  (adapter: $($cfg.InterfaceAlias))"

if (-not (Get-NetFirewallRule -DisplayName "SmartCane demo" -ErrorAction SilentlyContinue)) {
  Warn "Windows Firewall may block your phone. Run once in an ADMIN PowerShell:"
  Warn '  New-NetFirewallRule -DisplayName "SmartCane demo" -Direction Inbound -Protocol TCP -LocalPort 8000,8765 -Action Allow -Profile Any'
}

Step "Starting the API ($(if ($Local) { 'local database' } else { 'Tiger Cloud, from .env' }))"
if ($Local) {
  $env:DATABASE_URL = "postgresql+psycopg://postgres:devpass@db:5432/smartcane"
  docker compose --profile local up -d --build api
} else {
  docker compose up -d --build api
}
if ($LASTEXITCODE -ne 0) { Fail "docker compose failed (see the message above)." }

Step "Waiting for the API to be healthy"
$ok = $false
for ($i = 0; $i -lt 40; $i++) {
  try { if ((Invoke-RestMethod -Uri "http://localhost:8000/health" -TimeoutSec 3).status -eq "ok") { $ok = $true; break } } catch { }
  Start-Sleep -Seconds 2
}
if (-not $ok) { docker compose logs --tail 20 api; Fail "The API did not become healthy. If you use Tiger Cloud, check the internet connection and DATABASE_URL in .env; or try -Local." }

Step "Loading demo data (safe to repeat)"
docker compose exec -T api python -m backend.app.seed | Out-Null
if ($Simulated) {
  docker compose exec -T api python -m backend.app.register_device cane-sim --sensor-model simulated | Out-Null
  Step "Starting the simulated cane in its own window"
  Start-Process -FilePath python -ArgumentList "-m", "cane.run_sim" -WorkingDirectory $root -WindowStyle Minimized
  Start-Sleep -Seconds 4
}

if ($CaneUrl -ne "") {
  Step "Registering the real cane ($CaneDeviceId) to the LIVE patient"
  docker compose exec -T api python -m backend.app.register_device $CaneDeviceId --live | Out-Null
}

$api = "http://${ip}:8000"
if ($CaneUrl -ne "") { $cane = $CaneUrl } elseif ($Simulated) { $cane = "http://${ip}:8765" } else { $cane = "" }

Write-Host ""
Write-Host "READY" -ForegroundColor Green
Write-Host "  Backend : $api      (test on the phone's browser: $api/health)"
if ($cane -ne "") { Write-Host "  Cane    : $cane" } else { Warn "No cane address given. Set 'Cane address' in the app, or rerun with -CaneUrl or -Simulated." }
Write-Host "  Logins (password demo-password-1):"
Write-Host "    clinician@demo.example  - sees both patients"
Write-Host "    patient@demo.example    - 8 weeks of SIMULATED history$(if ($Simulated) { ' + the simulated cane' })"
Write-Host "    live@demo.example       - the LIVE patient$(if ($CaneUrl -ne '') { ' (your real cane syncs here)' } else { ' (no real cane connected yet)' })"
Write-Host ""

if ($NoExpo) { Write-Host "(-NoExpo: not starting Expo.)"; exit 0 }

Step "Starting Expo (scan the QR code with Expo Go). Press Ctrl+C to stop Expo."
$env:EXPO_PUBLIC_API_URL = $api
if ($cane -ne "") { $env:EXPO_PUBLIC_CANE_URL = $cane }
Set-Location (Join-Path $root "mobile")
npx expo start --clear
