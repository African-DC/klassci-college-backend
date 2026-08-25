$ErrorActionPreference = 'Stop'
Set-Location C:\klassci\backend

if (-not (Test-Path .\venv\Scripts\python.exe)) {
    Write-Host 'Creating venv...'
    python -m venv venv
}
Write-Host 'Upgrading pip...'
.\venv\Scripts\python.exe -m pip install --upgrade pip --quiet
Write-Host 'Installing requirements (this takes a few minutes)...'
.\venv\Scripts\python.exe -m pip install -r requirements.txt
Write-Host "PIP_EXIT=$LASTEXITCODE"
.\venv\Scripts\python.exe -c "import fastapi, sqlalchemy, aiomysql, alembic, weasyprint; print('imports OK', fastapi.__version__)"
Write-Host 'DONE'
