<#  Stops everything start-demo.ps1 started.   .\scripts\stop-demo.ps1  #>
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
Write-Host "==> Stopping the simulated cane" -ForegroundColor Cyan
Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
  Where-Object { $_.CommandLine -like "*cane.run_sim*" } |
  ForEach-Object { Stop-Process -Id $_.ProcessId -Force }
Write-Host "==> Stopping the API (and the local database, if it was running)" -ForegroundColor Cyan
docker compose --profile local down
Write-Host "Done. (Expo stops with Ctrl+C in its own window.)"
