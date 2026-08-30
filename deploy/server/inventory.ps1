$ErrorActionPreference = 'SilentlyContinue'
$os   = Get-CimInstance Win32_OperatingSystem
$cs   = Get-CimInstance Win32_ComputerSystem
$cpu  = Get-CimInstance Win32_Processor
$disk = Get-PSDrive C

Write-Host "OS            : $($os.Caption) build $($os.BuildNumber)"
Write-Host "RAM_GB        : $([math]::Round($cs.TotalPhysicalMemory/1GB,1))"
Write-Host "CPU           : $($cpu.Name)"
Write-Host "Cores         : phys=$($cpu.NumberOfCores) logical=$($cpu.NumberOfLogicalProcessors)"
Write-Host "Disk_C_free_GB: $([math]::Round($disk.Free/1GB,1)) / $([math]::Round(($disk.Used+$disk.Free)/1GB,1))"
Write-Host "Hypervisor    : $($cs.HypervisorPresent)"
Write-Host "VirtFW        : $($cpu.VirtualizationFirmwareEnabled)"

Write-Host "--- WSL ---"
$wsl = (Get-Command wsl.exe -ErrorAction SilentlyContinue)
if ($wsl) { Write-Host "wsl.exe       : present"; cmd /c "wsl --status 2>&1"; cmd /c "wsl -l -v 2>&1" }
else { Write-Host "wsl.exe       : ABSENT" }

Write-Host "--- Docker ---"
$docker = (Get-Command docker.exe -ErrorAction SilentlyContinue)
if ($docker) { Write-Host "docker        : $((docker --version) 2>&1)" } else { Write-Host "docker        : ABSENT" }

Write-Host "--- Other runtimes ---"
$py = (Get-Command python.exe -ErrorAction SilentlyContinue)
Write-Host "python        : $(if($py){(python --version) 2>&1}else{'ABSENT'})"
$node = (Get-Command node.exe -ErrorAction SilentlyContinue)
Write-Host "node          : $(if($node){(node --version) 2>&1}else{'ABSENT'})"
$git = (Get-Command git.exe -ErrorAction SilentlyContinue)
Write-Host "git           : $(if($git){(git --version) 2>&1}else{'ABSENT'})"

Write-Host "--- Internet egress ---"
try { $ip = Invoke-RestMethod 'https://api.ipify.org' -TimeoutSec 10; Write-Host "public_ip     : $ip" } catch { Write-Host "public_ip     : FAIL" }
Write-Host "DONE"
