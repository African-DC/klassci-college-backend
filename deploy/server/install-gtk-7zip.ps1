$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$target = 'C:\gtk3'
Write-Host '=== ensure 7zip ==='
if (-not (Get-Command 7z.exe -ErrorAction SilentlyContinue) -and -not (Test-Path 'C:\Program Files\7-Zip\7z.exe')) {
    choco install -y --no-progress 7zip | Out-Null
}
$sevenz = (Get-Command 7z.exe -ErrorAction SilentlyContinue).Source
if (-not $sevenz) { $sevenz = 'C:\Program Files\7-Zip\7z.exe' }

$url = 'https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases/download/2022-01-04/gtk3-runtime-3.24.31-2022-01-04-ts-win64.exe'
$exe = "$env:TEMP\gtk3-runtime.exe"
if (-not (Test-Path $exe)) { Write-Host 'downloading...'; Invoke-WebRequest -Uri $url -OutFile $exe }

Write-Host '=== 7z extract ==='
if (Test-Path $target) { Remove-Item $target -Recurse -Force }
& $sevenz x $exe "-o$target" -y | Out-Null

$dll = Get-ChildItem $target -Recurse -Filter 'libgobject-2.0-0.dll' -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $dll) { Write-Host 'GTK_DLL_NOT_FOUND'; Get-ChildItem $target | Select Name; exit 1 }
$bin = $dll.DirectoryName
Write-Host "GTK bin = $bin"

Write-Host '=== add to system PATH ==='
$cur = [Environment]::GetEnvironmentVariable('Path','Machine')
if ($cur -notlike "*$bin*") { [Environment]::SetEnvironmentVariable('Path', "$cur;$bin", 'Machine'); Write-Host 'PATH updated' }

Write-Host '=== verify weasyprint with this bin ==='
$env:Path = "$bin;$env:Path"
& 'C:\klassci\backend\venv\Scripts\python.exe' -c "from weasyprint import HTML; print('WEASYPRINT_OK')"
if ($LASTEXITCODE -ne 0) { Write-Host 'WEASYPRINT_IMPORT_FAILED'; exit 1 }

Write-Host '=== restart backend (inherit new PATH) ==='
nssm restart klassci-backend
Start-Sleep -Seconds 5
Write-Host 'GTK_7Z_DONE'
