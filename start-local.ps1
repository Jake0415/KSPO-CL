$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot
docker compose up -d --build
if ($LASTEXITCODE -ne 0) { throw 'Docker Compose startup failed' }
Write-Host 'Console: http://localhost:3334 (credentials: LOCAL_ACCESS.txt)'
