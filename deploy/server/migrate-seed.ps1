$ErrorActionPreference = 'Stop'
Set-Location C:\klassci\backend
$env:TENANT_ID = 'local'
$py = '.\venv\Scripts\python.exe'

Write-Host '=== alembic upgrade head (tenant=local) ==='
& $py -m alembic upgrade head
if ($LASTEXITCODE -ne 0) { Write-Host "ALEMBIC_FAILED=$LASTEXITCODE"; exit 1 }

Write-Host '=== seed test users ==='
& $py scripts\seed_test_users.py
if ($LASTEXITCODE -ne 0) { Write-Host "SEED_USERS_FAILED=$LASTEXITCODE"; exit 1 }

Write-Host '=== seed permissions + roles ==='
& $py scripts\seed_local_permissions.py
if ($LASTEXITCODE -ne 0) { Write-Host "SEED_PERMS_FAILED=$LASTEXITCODE"; exit 1 }

Write-Host 'MIGRATE_SEED_DONE'
