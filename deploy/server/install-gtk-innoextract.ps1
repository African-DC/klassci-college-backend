$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$target = 'C:\gtk3'
$bin = "$target\bin"
$dll = "$bin\libgobject-2.0-0.dll"
if (Test-Path $dll) { Write-Host 'GTK already extracted.'; }
else {
    Write-Host '=== install innoextract ==='
    choco install -y --no-progress innoextract | Out-Null

    $url = 'https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases/download/2022-01-04/gtk3-runtime-3.24.31-2022-01-04-ts-win64.exe'
    $exe = "$env:TEMP\gtk3-runtime.exe"
    if (-not (Test-Path $exe)) { Write-Host 'downloading installer...'; Invoke-WebRequest -Uri $url -OutFile $exe }

    Write-Host '=== innoextract (no GUI) ==='
    $ie = (Get-ChildItem 'C:\ProgramData\chocolatey\lib\innoextract' -Recurse -Filter innoextract.exe | Select-Object -First 1).FullName
    New-Item -ItemType Directory -Force -Path $target | Out-Null
    & $ie -e -s -d $target $exe
    # innoextract met les fichiers sous $target\app — on aplatit vers $target
    if (Test-Path "$target\app") {
        Get-ChildItem "$target\app" | ForEach-Object { Move-Item $_.FullName $target -Force }
        Remove-Item "$target\app" -Recurse -Force
    }
}

if (-not (Test-Path $dll)) { Write-Host 'GTK_DLL_MISSING after extract'; Get-ChildItem $target | Select Name; exit 1 }

Write-Host '=== add to system PATH ==='
$cur = [Environment]::GetEnvironmentVariable('Path','Machine')
if ($cur -notlike "*$bin*") {
    [Environment]::SetEnvironmentVariable('Path', "$cur;$bin", 'Machine')
    Write-Host "added $bin to machine PATH"
}

Write-Host '=== restart backend so it inherits new PATH ==='
nssm restart klassci-backend
Start-Sleep -Seconds 5
& 'C:\klassci\backend\venv\Scripts\python.exe' -c "import os; os.environ['PATH']=os.environ['PATH']+r';$bin'; from weasyprint import HTML; print('WEASYPRINT_OK')"
Write-Host 'GTK_DONE'
