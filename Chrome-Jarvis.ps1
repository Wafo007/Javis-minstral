# Lance Chrome avec le port de debug pour que Jarvis puisse t'assister.
# Depuis Chrome 136+, le debug est interdit sur le profil par defaut : on utilise
# donc un profil dedie "ChromeJarvis" (connecte-toi une fois a tes sites dedans,
# ca reste memorise). Double-clique "Chrome + Jarvis.bat" pour lancer ceci.

$port   = 9222
$profil = Join-Path $env:LOCALAPPDATA "ChromeJarvis"

$chrome = Join-Path $env:ProgramFiles "Google\Chrome\Application\chrome.exe"
if (-not (Test-Path $chrome)) {
    $chrome = Join-Path ${env:ProgramFiles(x86)} "Google\Chrome\Application\chrome.exe"
}
if (-not (Test-Path $chrome)) {
    Write-Host "Chrome introuvable. Installe Google Chrome, ou modifie ce script." -ForegroundColor Red
    Start-Sleep 4; exit 1
}

# Deja lance ? (port de debug deja ouvert)
$dejaLance = $false
try {
    $c = New-Object Net.Sockets.TcpClient
    $c.Connect("localhost", $port); $dejaLance = $c.Connected; $c.Close()
} catch { }

if ($dejaLance) {
    Write-Host "Chrome + Jarvis tourne deja (port $port). Rien a faire." -ForegroundColor Green
    Start-Sleep 2; exit 0
}

Write-Host "Lancement de Chrome + Jarvis (profil dedie, port $port)..." -ForegroundColor Cyan
& $chrome "--remote-debugging-port=$port" "--user-data-dir=$profil"
