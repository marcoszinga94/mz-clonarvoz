# Lanza la app visual en Windows y abre el navegador.
#   .\app.ps1          → http://127.0.0.1:8000
#   .\app.ps1 8100     → otro puerto
#   $env:NO_OPEN = 1   → no abre el navegador
$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$py = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) {
    Write-Host 'Falta el entorno. Corre: uv venv --python 3.11 .venv'
    Write-Host 'y después: uv pip install --torch-backend=cpu -r requirements.txt'
    exit 1
}

$port = if ($env:PORT) { [int]$env:PORT } else { 8000 }
if ($args.Count -gt 0 -and "$($args[0])" -match '^\d+$') { $port = [int]$args[0] }
$url = "http://127.0.0.1:$port"

if ("$env:NO_OPEN" -ne '1') {
    Start-Job -ScriptBlock { param($u) Start-Sleep -Seconds 2; Start-Process $u } -ArgumentList $url | Out-Null
}

Write-Host "ClonarVoz en $url  (Ctrl+C para salir)"
& $py -m uvicorn servidor:app --host 127.0.0.1 --port $port --log-level warning
