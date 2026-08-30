# Pointer WeasyPrint 69 vers le dossier GTK, faute de quoi tous les documents
# officiels tombent en 500.
#
# Depuis la version 69, WeasyPrint s'appuie sur `os.add_dll_directory`, qui ne
# lit que `WEASYPRINT_DLL_DIRECTORIES` et plus le `PATH` machine. La 62.3 s'en
# contentait. Le symptome est trompeur : la DLL nommee dans l'erreur existe,
# c'est une de ses dependances que le chargeur ne trouve plus (erreur 0x7e,
# ERROR_MOD_NOT_FOUND).
#
# Le dossier est cherche plutot qu'ecrit en dur : il porte un nom d'extraction
# NSIS (`$_63_`) qu'un shell mange a la premiere occasion.

$ErrorActionPreference = 'Stop'

$gtk = (Get-ChildItem C:\gtk3 -Recurse -Filter "libgobject-2.0-0.dll" -ErrorAction SilentlyContinue |
        Select-Object -First 1).DirectoryName

if (-not $gtk) {
    Write-Host "GTK introuvable sous C:\gtk3 — lancer install-gtk-7zip.ps1 d'abord."
    exit 1
}

Write-Output "dossier GTK : $gtk"
& nssm set klassci-backend AppEnvironmentExtra "WEASYPRINT_DLL_DIRECTORIES=$gtk"
& nssm get klassci-backend AppEnvironmentExtra
Write-Output "Redemarrer le service, puis regenerer un recu pour verifier."
