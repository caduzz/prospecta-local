# Sobe tudo do Prospecta no Windows: Docker Desktop, Evolution API (WhatsApp) e o servidor.
# Use pelo iniciar.bat (duplo clique). Feche a janela para desligar o Prospecta.
$proj = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $env:USERPROFILE '.venvs\prospecta-local\Scripts\python.exe'
$dockerExe = 'C:\Program Files\Docker\Docker\Docker Desktop.exe'

function Test-Docker { docker info --format '{{.ServerVersion}}' 2>$null }

if (-not (Test-Docker)) {
    # O Docker Desktop às vezes trava ao iniciar por causa de sockets antigos na pasta run.
    # Com ele fechado, renomear a pasta é seguro: ele cria uma nova.
    if (-not (Get-Process 'Docker Desktop' -ErrorAction SilentlyContinue)) {
        $run = Join-Path $env:LOCALAPPDATA 'Docker\run'
        if (Test-Path $run) { Rename-Item $run ('run.antigo-' + (Get-Date -Format 'yyyyMMdd-HHmmss')) -ErrorAction SilentlyContinue }
        Start-Process $dockerExe
    }
    Write-Host 'Aguardando o Docker iniciar...'
    for ($i = 0; $i -lt 80 -and -not (Test-Docker); $i++) { Start-Sleep -Seconds 3 }
    if (-not (Test-Docker)) { Write-Host 'O Docker não iniciou. Abra o Docker Desktop manualmente e rode de novo.'; Read-Host 'Enter para sair'; exit 1 }
}

Set-Location $proj
Write-Host 'Subindo a Evolution API (WhatsApp)...'
docker compose -f docker-compose.evolution.yml up -d

Write-Host 'Abrindo o Prospecta em http://127.0.0.1:8000'
Start-Process 'http://127.0.0.1:8000'
& $python -m uvicorn app:app --host 127.0.0.1 --port 8000
