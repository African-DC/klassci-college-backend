$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path C:\klassci\logs, C:\klassci\deploy | Out-Null

# --- Resolve real exe paths (avoid choco shims under NSSM) ---
$node = (Get-Command node.exe).Source
$caddy = (Get-ChildItem 'C:\ProgramData\chocolatey\lib\caddy' -Recurse -Filter caddy.exe -ErrorAction SilentlyContinue | Select-Object -First 1).FullName
if (-not $caddy) { $caddy = (Get-Command caddy).Source }
Write-Host "node=$node"
Write-Host "caddy=$caddy"

function Reset-Svc($name) {
  $e = Get-Service $name -ErrorAction SilentlyContinue
  if ($e) { nssm stop $name; nssm remove $name confirm }
}

# ================= FRONTEND (Next.js standalone) =================
Reset-Svc 'klassci-frontend'
nssm install klassci-frontend $node
nssm set klassci-frontend AppParameters "C:\klassci\frontend\.next\standalone\server.js"
nssm set klassci-frontend AppDirectory "C:\klassci\frontend\.next\standalone"
$envBlock = @(
  "NODE_ENV=production",
  "PORT=3000",
  "HOSTNAME=127.0.0.1",
  "NEXTAUTH_URL=http://94.72.96.119",
  "AUTH_URL=http://94.72.96.119",
  "NEXTAUTH_SECRET=S7fXdAkAZBW/A6/Ye6KagOEdLd1+doaamfMCPjo29LM=",
  "AUTH_SECRET=S7fXdAkAZBW/A6/Ye6KagOEdLd1+doaamfMCPjo29LM=",
  "AUTH_TRUST_HOST=true"
) -join "`n"
nssm set klassci-frontend AppEnvironmentExtra $envBlock
nssm set klassci-frontend AppStdout "C:\klassci\logs\frontend.out.log"
nssm set klassci-frontend AppStderr "C:\klassci\logs\frontend.err.log"
nssm set klassci-frontend AppRotateFiles 1
nssm set klassci-frontend AppRotateBytes 10485760
nssm set klassci-frontend Start SERVICE_AUTO_START
nssm start klassci-frontend

# ================= CADDY (reverse proxy :80) =================
Reset-Svc 'klassci-caddy'
nssm install klassci-caddy $caddy
nssm set klassci-caddy AppParameters "run --config C:\klassci\deploy\Caddyfile"
nssm set klassci-caddy AppDirectory "C:\klassci\deploy"
nssm set klassci-caddy AppStdout "C:\klassci\logs\caddy.out.log"
nssm set klassci-caddy AppStderr "C:\klassci\logs\caddy.err.log"
nssm set klassci-caddy AppRotateFiles 1
nssm set klassci-caddy AppRotateBytes 10485760
nssm set klassci-caddy Start SERVICE_AUTO_START
nssm start klassci-caddy

Start-Sleep -Seconds 6
Get-Service klassci-backend,klassci-frontend,klassci-caddy | Select-Object Name,Status | Format-Table -AutoSize
Write-Host 'SERVICES_SET'
