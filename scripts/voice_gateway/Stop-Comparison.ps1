$ErrorActionPreference='Stop'
$repo=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$stateFile=Join-Path $repo 'tmp\asr-comparison-20261020\manual-gateway\gateway-process.json'
if (!(Test-Path -LiteralPath $stateFile)) { throw 'Nao ha registro do gateway experimental manual.' }
$state=Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
Invoke-RestMethod -Method Post -Uri ('http://127.0.0.1:'+$state.port+'/shutdown') -Headers @{Authorization=('Bearer '+$state.shutdown_token)} -Body '{}' -ContentType 'application/json'
