$ErrorActionPreference = 'Stop'
Set-Location C:\klassci\backend
$env:TENANT_ID = 'local'
& .\venv\Scripts\python.exe -m alembic current
