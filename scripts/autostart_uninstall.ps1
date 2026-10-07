# Désinstalle le démarrage automatique de Jarvis (les deux méthodes possibles).
# Usage : powershell -ExecutionPolicy Bypass -File scripts\autostart_uninstall.ps1
$nom = "JarvisAutostart"
$retire = $false

# 1) Tâche planifiée (si présente).
if (Get-ScheduledTask -TaskName $nom -ErrorAction SilentlyContinue) {
  try {
    Unregister-ScheduledTask -TaskName $nom -Confirm:$false -ErrorAction Stop
    Write-Host "OK : tâche planifiée « $nom » supprimée." -ForegroundColor Green
    $retire = $true
  } catch {
    Write-Host "Tâche présente mais suppression refusée (relance en admin)." -ForegroundColor Yellow
  }
}

# 2) Raccourci du dossier Démarrage (si présent).
$cmd = Join-Path ([Environment]::GetFolderPath('Startup')) "JarvisAutostart.cmd"
if (Test-Path $cmd) {
  Remove-Item $cmd -Force
  Write-Host "OK : lancement au démarrage retiré ($cmd)." -ForegroundColor Green
  $retire = $true
}

if (-not $retire) { Write-Host "Rien à retirer (aucun démarrage auto installé)." }
