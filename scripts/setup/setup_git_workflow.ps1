$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

Push-Location $repoRoot
try {
    git config core.hooksPath .githooks
    git config commit.template .gitmessage.txt

    Write-Host "Git workflow configured for this repository."
    Write-Host " - core.hooksPath=.githooks"
    Write-Host " - commit.template=.gitmessage.txt"
    Write-Host ""
    Write-Host "Current values:"
    git config --get core.hooksPath
    git config --get commit.template
}
finally {
    Pop-Location
}
