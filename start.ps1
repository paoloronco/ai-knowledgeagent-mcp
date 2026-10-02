$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

docker info --format '{{.ServerVersion}}' *> $null
if ($LASTEXITCODE -ne 0) {
    throw 'Avvia Docker Desktop e riprova.'
}

$config = Join-Path $PSScriptRoot '.env'
$lines = if (Test-Path -LiteralPath $config) { @(Get-Content -LiteralPath $config) } else { @() }
if (-not ($lines | Where-Object { $_ -match '^KNOWLEDGE_HOST_PATH=' })) {
    do {
        $chosen = Read-Host 'Cartella dei documenti sul computer (percorso completo)'
        $valid = Test-Path -LiteralPath $chosen -PathType Container
        if (-not $valid) { Write-Host 'La cartella non esiste.' }
    } until ($valid)
    $resolved = (Resolve-Path -LiteralPath $chosen).Path.Replace('\', '/')
    $lines += "KNOWLEDGE_HOST_PATH=`"$resolved`""
    [System.IO.File]::WriteAllLines($config, [string[]]$lines, [System.Text.UTF8Encoding]::new($false))
}

docker compose config --quiet
if ($LASTEXITCODE -ne 0) { throw 'Configurazione Docker Compose non valida.' }
docker compose pull
if ($LASTEXITCODE -ne 0) { throw 'Impossibile scaricare le immagini Docker.' }
docker compose up -d
if ($LASTEXITCODE -ne 0) { throw 'Avvio Docker non riuscito. Controlla docker compose logs.' }

Write-Host "Web UI: http://$(docker compose port app 8080)"
Write-Host "MCP:    http://$(docker compose port app 8000)/mcp"
