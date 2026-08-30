$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path C:\klassci\logs | Out-Null

$svc = 'klassci-backend'
$py  = 'C:\klassci\backend\venv\Scripts\python.exe'

# Remove existing service if present (idempotent)
$existing = Get-Service $svc -ErrorAction SilentlyContinue
if ($existing) { nssm stop $svc; nssm remove $svc confirm }

nssm install $svc $py
nssm set $svc AppParameters "-m uvicorn app.main:app --host 127.0.0.1 --port 8000"
nssm set $svc AppDirectory "C:\klassci\backend"
nssm set $svc AppStdout "C:\klassci\logs\backend.out.log"
nssm set $svc AppStderr "C:\klassci\logs\backend.err.log"
nssm set $svc AppRotateFiles 1
nssm set $svc AppRotateBytes 10485760
nssm set $svc Start SERVICE_AUTO_START
nssm set $svc AppStopMethodConsole 5000
nssm start $svc
Start-Sleep -Seconds 6
Get-Service $svc | Select-Object Name,Status | Format-Table -AutoSize
Write-Host 'BACKEND_SERVICE_SET'
