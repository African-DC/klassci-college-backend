$ErrorActionPreference = 'Stop'
Set-Location C:\klassci\backend
$env:TENANT_ID = 'local'
& .\venv\Scripts\python.exe -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Host "ALEMBIC_FAILED=$LASTEXITCODE"; exit 1 }
& .\venv\Scripts\python.exe -m alembic current
Write-Host 'UPGRADE_DONE'
