# =====================================================================
# KLASSCI College — Bootstrap SSH (à exécuter UNE SEULE FOIS sur le
# serveur 94.72.96.119, via RDP, dans un PowerShell *Administrateur*).
#
# Ce script :
#   1. Installe + démarre OpenSSH Server (auto-start au boot)
#   2. Ouvre le port 22 dans le firewall
#   3. Installe la clé publique de déploiement (accès sans mot de passe)
#   4. Met PowerShell comme shell SSH par défaut
#
# Après ça, l'agent se connecte en SSH par clé et pilote tout le reste.
# =====================================================================

$ErrorActionPreference = 'Stop'

# --- Clé publique de déploiement (générée côté poste de dev) ---
$pubKey = 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB0rutO8qImpg3rz90PMXYqw7RfZDPxm3wcgIYzPaQ6M klassci-deploy@94.72.96.119'

Write-Host '== 1/4 Installation OpenSSH Server ==' -ForegroundColor Cyan
$cap = Get-WindowsCapability -Online | Where-Object Name -like 'OpenSSH.Server*'
if ($cap.State -ne 'Installed') {
    Add-WindowsCapability -Online -Name $cap.Name
} else {
    Write-Host 'Deja installe.'
}

Write-Host '== 2/4 Demarrage + auto-start du service ==' -ForegroundColor Cyan
Set-Service -Name sshd -StartupType Automatic
Start-Service sshd

Write-Host '== 3/4 Regle firewall port 22 ==' -ForegroundColor Cyan
if (-not (Get-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -ErrorAction SilentlyContinue)) {
    New-NetFirewallRule -Name 'OpenSSH-Server-In-TCP' -DisplayName 'OpenSSH Server (sshd)' `
        -Enabled True -Direction Inbound -Protocol TCP -Action Allow -LocalPort 22
} else {
    Write-Host 'Regle deja presente.'
}

Write-Host '== 4/4 Installation de la cle publique (admin) ==' -ForegroundColor Cyan
$adminKeys = "$env:ProgramData\ssh\administrators_authorized_keys"
if (-not (Test-Path $adminKeys) -or -not (Select-String -Path $adminKeys -SimpleMatch $pubKey -Quiet)) {
    Add-Content -Path $adminKeys -Value $pubKey
}
# ACL stricte requise par OpenSSH pour administrators_authorized_keys
icacls $adminKeys /inheritance:r | Out-Null
icacls $adminKeys /grant 'Administrators:F' 'SYSTEM:F' | Out-Null

# PowerShell comme shell SSH par defaut (scripting propre cote agent)
$psPath = (Get-Command powershell.exe).Source
New-ItemProperty -Path 'HKLM:\SOFTWARE\OpenSSH' -Name DefaultShell -Value $psPath `
    -PropertyType String -Force | Out-Null

Restart-Service sshd

Write-Host ''
Write-Host 'OK — SSH pret. IP publique de ce serveur :' -ForegroundColor Green
(Invoke-RestMethod -Uri 'https://api.ipify.org') 2>$null
Write-Host 'Teste depuis le poste de dev : ssh klassci'
