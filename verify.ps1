param (
    [switch]$Autoheal
)

function Log-Info {
    param([string]$Msg)
    Write-Host "[INFO] $Msg" -ForegroundColor Cyan
}

Write-Host "--- VERIFICATION UNIABSENCES ---" -ForegroundColor Magenta

# 1. Vérification des statuts
Log-Info "--- ETAT DES CONTENEURS ---"
docker compose ps

# 2. Vérification rapide des logs Django
Log-Info "--- DERNIERS LOGS WEB (Django) ---"
docker logs unabsences_web --tail 10

# 3. Vérification Uptime Kuma
Log-Info "--- MONITORING ---"
$kuma = docker ps -q -f name=unabsences_monitoring
if ($kuma) {
    Write-Host "✅ Uptime Kuma est en ligne sur http://localhost:3001" -ForegroundColor Green
} else {
    Write-Host "❌ Uptime Kuma semble éteint" -ForegroundColor Red
}

# 4. Test Autoheal (Optionnel)
if ($Autoheal) {
    Log-Info "--- TEST AUTOHEAL (CRASH TEST) ---"
    Write-Host "ATTENTION : Sabotage du conteneur en cours..." -ForegroundColor Yellow
    
    # CORRECTION ICI : On utilise 'kill 1' car 'pkill' n'existe pas dans l'image slim
    docker exec unabsences_web sh -c "kill 1"
    
    Log-Info "☠️  Processus tué. Attente de la réaction d'Autoheal..."
    
    # On attend 40 secondes (Autoheal réagit vite maintenant)
    for ($i = 1; $i -le 40; $i++) {
        Write-Progress -Activity "Réparation en cours par Autoheal" -Status "$i / 40 secondes" -PercentComplete (($i / 40) * 100)
        Start-Sleep -Seconds 1
    }
    
    Log-Info "--- RESULTAT APRES ATTENTE ---"
    # On vérifie si le conteneur vient de redémarrer (STATUS < 1 minute)
    docker ps --filter "name=unabsences_web"
    
    Log-Info "--- PREUVE DANS LES LOGS AUTOHEAL ---"
    docker logs unabsences_autoheal --tail 5
} else {
    Write-Host "
[TIP] Pour tester la réparation automatique, lancez : .\verify.ps1 -Autoheal" -ForegroundColor Gray
}
