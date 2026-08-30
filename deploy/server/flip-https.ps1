$ErrorActionPreference = 'Stop'

Write-Host '== 1. open firewall 443 =='
if (-not (Get-NetFirewallRule -Name 'HTTPS-In-TCP-443' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'HTTPS-In-TCP-443' -DisplayName 'HTTPS (443)' -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 443 | Out-Null
    Write-Host 'rule created'
} else { Write-Host 'rule exists' }

Write-Host '== 2. backend CORS -> https + restart =='
$envPath = 'C:\klassci\backend\.env'
$content = Get-Content $envPath -Raw
$content = $content -replace 'CORS_ORIGINS=.*', 'CORS_ORIGINS=["https://college.klassci.com","http://94.72.96.119"]'
Set-Content -Path $envPath -Value $content -NoNewline
nssm restart klassci-backend | Out-Null

Write-Host '== 3. rebuild frontend (new domain baked in) =='
powershell -NoProfile -ExecutionPolicy Bypass -File C:\klassci-deploy\frontend-build.ps1
if ($LASTEXITCODE -ne 0) { Write-Host 'FRONTEND_REBUILD_FAILED'; exit 1 }
nssm restart klassci-frontend | Out-Null

Write-Host '== 4. swap Caddy to HTTPS config + restart =='
Copy-Item C:\klassci\deploy\Caddyfile.https C:\klassci\deploy\Caddyfile -Force
nssm restart klassci-caddy | Out-Null
Start-Sleep -Seconds 8
Get-Service klassci-backend,klassci-frontend,klassci-caddy | Select Name,Status | Format-Table -AutoSize
Write-Host 'FLIP_HTTPS_DONE'
