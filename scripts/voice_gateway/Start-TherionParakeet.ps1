$ErrorActionPreference='Stop'
$repo=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$config=Get-Content -LiteralPath (Join-Path $env:APPDATA 'Therion\config.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($config.voice.provider -ne 'parakeet_http' -or $config.tts.voicestudio_endpoint -ne 'http://127.0.0.1:3902/v1/audio/speech') { throw 'Ative a configuracao do teste antes de abrir.' }
function Get-State([string]$Url) {
    try { return (Invoke-RestMethod -Uri $Url -TimeoutSec 3) } catch { return $null }
}
if (!(Get-NetTCPConnection -LocalPort 3901 -State Listen -ErrorAction SilentlyContinue)) {
    & (Join-Path $repo 'scripts\omnivoice_minimal\Start-VoiceMinimal.ps1')
}
$timer=[Diagnostics.Stopwatch]::StartNew()
while ((Get-State 'http://127.0.0.1:3901/health').status -ne 'ready') {
    if ($timer.Elapsed.TotalSeconds -gt 300) { throw 'Jarvis nao ficou pronto; nao houve troca de voz.' }
    Start-Sleep -Seconds 2
}
if (!(Get-NetTCPConnection -LocalPort 3902 -State Listen -ErrorAction SilentlyContinue)) {
    & (Join-Path $PSScriptRoot 'Start-Comparison.ps1') -Model parakeet
}
$timer.Restart()
do {
    $state=Get-State 'http://127.0.0.1:3902/health'
    if ($state.status -eq 'ready' -and $state.model -eq 'parakeet') { break }
    if ($timer.Elapsed.TotalSeconds -gt 90) { throw 'Parakeet nao ficou pronto.' }
    Start-Sleep -Seconds 1
} while ($true)
& (Join-Path $repo 'scripts\start-local-ollama.ps1')
$timer.Restart()
while (!(Get-State 'http://127.0.0.1:11435/api/version')) {
    if ($timer.Elapsed.TotalSeconds -gt 90) { throw 'Ollama nao ficou pronto.' }
    Start-Sleep -Seconds 1
}
Write-Output 'Preparando a mesma IA local antes de abrir o Therion...'
$body=@{model=$config.ai.model;messages=@(@{role='user';content='Responda somente OK.'});think=$false;stream=$false;keep_alive='30m';options=@{num_ctx=8192;num_predict=8}} | ConvertTo-Json -Depth 8 -Compress
$warm=Invoke-RestMethod -Method Post -Uri $config.ai.endpoint -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body)) -TimeoutSec 240
if (!$warm.done -or !$warm.message.content) { throw 'A IA nao confirmou prontidao.' }
$runtime=Join-Path $repo 'tmp\parakeet-therion-20261020'
@{status='ready';ai_model=$config.ai.model;stt='parakeet';voice='120f734a';utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'launch-result.json') -Encoding UTF8
Start-Process -FilePath (Join-Path $repo '.venv\Scripts\pythonw.exe') -ArgumentList @('-m','therion.interface.desktop') -WorkingDirectory $repo -WindowStyle Hidden
Write-Output 'Therion aberto com Parakeet e Jarvis. Use Conversar por voz.'
