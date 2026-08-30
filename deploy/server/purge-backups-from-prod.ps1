# Purge les archives recues de la production au-dela de 30 jours.
#
# La production ne peut PAS supprimer ici : sa cle est restreinte au seul depot
# de fichiers (`restrict,command="scp -t ..."` dans
# C:\ProgramData\ssh\administrators_authorized_keys). C'est voulu — un serveur
# qui porte des donnees d'eleves n'a aucune raison de pouvoir effacer ailleurs.
# La retention vit donc du cote qui recoit.
#
# Planifie a 04h00 par une tache Windows tournant sous SYSTEM.
$dossier = "C:\klassci-backups\from-prod"
$limite = (Get-Date).AddDays(-30)
Get-ChildItem $dossier -Filter *.tar.gz -ErrorAction SilentlyContinue |
    Where-Object { $_.LastWriteTime -lt $limite } |
    Remove-Item -Force
$restants = (Get-ChildItem $dossier -Filter *.tar.gz -ErrorAction SilentlyContinue).Count
"$(Get-Date -Format s) purge faite, $restants archive(s) conservee(s)"
