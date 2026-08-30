$ErrorActionPreference = 'Stop'
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$dll = 'C:\Program Files\GTK3-Runtime Win64\bin\libgobject-2.0-0.dll'
if (Test-Path $dll) { Write-Host 'GTK already installed.'; exit 0 }

$url = 'https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases/download/2022-01-04/gtk3-runtime-3.24.31-2022-01-04-ts-win64.exe'
$out = "$env:TEMP\gtk3-runtime.exe"
Write-Host 'Downloading GTK3 runtime...'
Invoke-WebRequest -Uri $url -OutFile $out
Write-Host 'Installing (silent)...'
Start-Process -FilePath $out -ArgumentList '/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART' -Wait
if (Test-Path $dll) { Write-Host 'GTK installed OK.' } else { Write-Host 'GTK install FAILED'; exit 1 }
