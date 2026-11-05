param([switch]$StartMinimized,[switch]$Quiet,[switch]$CheckOnly,[switch]$PrepareOnly)
$ErrorActionPreference='Stop'
$repo=Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'VoiceStartup.ps1')
$stateRoot=Join-Path $env:LOCALAPPDATA 'Therion\voice'
$configPath=Join-Path $env:APPDATA 'Therion\config.json'
$config=Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$sttProfile=Get-TherionSttProfile $config
$installation=Get-Content -LiteralPath (Join-Path $stateRoot 'installation.json') -Raw -Encoding UTF8 | ConvertFrom-Json
if ($installation.profile -ne '120f734a' -or $installation.device -ne 'cuda' -or $installation.steps -ne 16) { throw 'Instalacao da voz nao corresponde ao perfil aprovado.' }
if ((Get-FileHash -LiteralPath (Join-Path $installation.voice_runtime 'profile.json')).Hash.ToLowerInvariant() -ne $installation.profile_sha256 -or
    (Get-FileHash -LiteralPath (Join-Path $installation.voice_runtime $installation.reference_cache)).Hash.ToLowerInvariant() -ne $installation.reference_cache_sha256) { throw 'Perfil ou cache da referencia foi alterado.' }
function Send-LocalJson([string]$Url,[object]$Payload,[int]$Timeout=240,[switch]$Audio) {
    $bytes=[Text.Encoding]::UTF8.GetBytes(($Payload | ConvertTo-Json -Depth 8 -Compress))
    $request=[Net.HttpWebRequest]::Create($Url)
    $request.Proxy=$null;$request.AllowAutoRedirect=$false;$request.Method='POST'
    $request.ContentType='application/json';$request.ContentLength=$bytes.Length
    $request.Timeout=$Timeout*1000;$request.ReadWriteTimeout=$Timeout*1000
    $stream=$request.GetRequestStream()
    try { $stream.Write($bytes,0,$bytes.Length) } finally { $stream.Dispose() }
    # Nunca repetir POST depois de erro ou timeout.
    $response=$request.GetResponse()
    try {
        if ($Audio) {
            $output=[IO.MemoryStream]::new()
            try { $response.GetResponseStream().CopyTo($output);return ,($output.ToArray()) } finally { $output.Dispose() }
        }
        $reader=[IO.StreamReader]::new($response.GetResponseStream())
        try { return ($reader.ReadToEnd() | ConvertFrom-Json) } finally { $reader.Dispose() }
    } finally { $response.Close() }
}
if ($CheckOnly) {
    $voice=Read-LocalState 'http://127.0.0.1:3901/health'
    $gateway=Read-LocalState 'http://127.0.0.1:3902/health'
    $ollama=Read-LocalState 'http://127.0.0.1:11435/api/version'
    @{voice=$voice.status;transcription=$gateway.status;model=$gateway.model;ollama=[bool]$ollama;state_root=$stateRoot;changed_configuration=$false} | ConvertTo-Json -Compress
    return
}
$startupMutex=[Threading.Mutex]::new($false,'Local\TherionVoiceStartup')
$ownsMutex=$false
$transcript=$false
try {
    try { $ownsMutex=$startupMutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $ownsMutex=$true }
    if (!$ownsMutex) { Write-Output 'Therion ja esta sendo preparado.';return }
    if (!$PrepareOnly) {
        $existing=Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like ('*'+$repo+'*') -and $_.CommandLine -like '*-m therion.interface.desktop*' }
        if ($existing) { Write-Output 'Therion ja esta aberto. Use a janela ou o icone na bandeja.';return }
    }
    Start-Transcript -LiteralPath (Join-Path $stateRoot 'startup.log') -Force | Out-Null
    $transcript=$true
    Write-Output ('Preparando '+$(if($sttProfile -eq 'parakeet'){'Parakeet'}else{'faster-whisper'})+', Jarvis e a IA local. A primeira carga pode levar alguns minutos.')
    if (!(Get-NetTCPConnection -LocalPort 3901 -State Listen -ErrorAction SilentlyContinue)) {
        $models=Read-LocalState 'http://127.0.0.1:11435/api/ps'
        if ($models.models | Where-Object { $_.name -eq $config.ai.model }) {
            Send-LocalJson ($config.ai.endpoint.Replace('/api/chat','/api/generate')) @{model=$config.ai.model;keep_alive=0;stream=$false} 30 | Out-Null
        }
        & (Join-Path $PSScriptRoot 'omnivoice_minimal\Start-VoiceMinimal.ps1') -RuntimeRoot $installation.voice_runtime
    }
    $timer=[Diagnostics.Stopwatch]::StartNew()
    do {
        $voice=Read-LocalState 'http://127.0.0.1:3901/startup/progress'
        if ($voice.status -eq 'error') { throw ('Jarvis falhou em '+$voice.phase+': '+$voice.failure_type) }
        if ($voice.status -eq 'ready') { break }
        if ($timer.Elapsed.TotalSeconds -gt 900) { throw 'Jarvis nao ficou pronto.' } # boot frio no HD chega a ~9 min
        Start-Sleep -Seconds 2
    } while ($true)
    $profile=Read-LocalState 'http://127.0.0.1:3901/profiles/120f734a'
    if ($profile.id -ne '120f734a') { throw 'Perfil Jarvis nao confirmado.' }
    # No perfil faster-whisper a transcricao carrega dentro do Therion; o gateway 3902 nao e usado.
    if ($sttProfile -eq 'parakeet') {
        $gateway=Read-LocalState 'http://127.0.0.1:3902/stt/health'
        $gatewayAction=Get-ParakeetStartupAction $gateway (Get-TherionAvailableCommit)
        if ($gatewayAction -eq 'restart') {
            Write-Output 'Reiniciando apenas o Parakeet que falhou, agora com memoria disponivel...'
            Stop-FailedTherionGateway $installation.gateway_runtime
            $gatewayAction='start'
        }
        if ($gatewayAction -eq 'start') {
            if (Get-NetTCPConnection -LocalPort 3902 -State Listen -ErrorAction SilentlyContinue) { throw 'A porta 3902 esta ocupada por um servico sem prontidao identificavel. Nenhum processo foi encerrado.' }
            $python='F:\VoiceStudio\runtime\project\.venv\Scripts\python.exe'
            $arguments=@(('"'+(Join-Path $PSScriptRoot 'voice_gateway\server.py')+'"'),'--model','parakeet','--runtime',('"'+$installation.gateway_runtime+'"'))
            Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput (Join-Path $installation.gateway_runtime 'stdout.log') -RedirectStandardError (Join-Path $installation.gateway_runtime 'stderr.log')
        }
        $timer.Restart()
        do {
            $gateway=Read-LocalState 'http://127.0.0.1:3902/stt/health'
            if ($gateway.status -eq 'ready' -and $gateway.model -eq 'parakeet') { break }
            if ($gateway.status -eq 'error') {
                $null=Get-ParakeetStartupAction $gateway (Get-TherionAvailableCommit)
                throw ('Parakeet falhou durante a carga: '+$gateway.failure_type+'. Nao houve repeticao automatica ou troca de modelo.')
            }
            if ($timer.Elapsed.TotalSeconds -gt 90) { throw 'Parakeet nao ficou pronto.' }
            Start-Sleep -Seconds 1
        } while ($true)
    }
    & (Join-Path $PSScriptRoot 'start-local-ollama.ps1')
    $timer.Restart()
    while (!(Read-LocalState 'http://127.0.0.1:11435/api/version')) {
        if ($timer.Elapsed.TotalSeconds -gt 90) { throw 'Ollama nao ficou pronto.' }
        Start-Sleep -Seconds 1
    }
    # Aquecer com o mesmo num_ctx do agente; outro valor faz o Ollama recarregar o modelo na primeira pergunta.
    $warmContext=8192
    if ($config.agent.context_tokens -is [int] -and $config.agent.context_tokens -ge 1024 -and $config.agent.context_tokens -le 16384) { $warmContext=$config.agent.context_tokens }
    $warm=Send-LocalJson $config.ai.endpoint @{model=$config.ai.model;messages=@(@{role='user';content='Responda somente OK.'});think=$false;stream=$false;keep_alive='5m';options=@{num_ctx=$warmContext;num_predict=8}}
    if (!$warm.done -or !$warm.message.content) { throw 'IA nao confirmou prontidao.' }
    if (!$voice.last_generation) {
        $warmAudio=Send-LocalJson 'http://127.0.0.1:3901/v1/audio/speech' @{model='tts-1';voice='120f734a';input='Ola.';language='pt';response_format='wav'} 90 -Audio
        if ($warmAudio.Length -lt 44 -or [Text.Encoding]::ASCII.GetString($warmAudio,0,4) -ne 'RIFF' -or [Text.Encoding]::ASCII.GetString($warmAudio,8,4) -ne 'WAVE') { throw 'Aquecimento da voz nao retornou WAV valido.' }
    }
    @{status='ready';stt=$sttProfile;voice='120f734a';model=$config.ai.model;utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $stateRoot 'launch-result.json') -Encoding UTF8
    if (!$PrepareOnly) {
        $arguments=@('-m','therion.interface.desktop')
        if ($StartMinimized) { $arguments+='--start-minimized' }
        Start-Process -FilePath (Join-Path $repo '.venv\Scripts\pythonw.exe') -ArgumentList $arguments -WorkingDirectory $repo -WindowStyle Hidden
    }
    Write-Output 'Therion pronto.'
} catch {
    $_ | Out-String | Set-Content -LiteralPath (Join-Path $stateRoot 'startup-error.txt') -Encoding UTF8
    if (!$Quiet) { Write-Host $_ -ForegroundColor Red;Read-Host 'Pressione Enter para fechar' | Out-Null }
    throw
} finally {
    if ($transcript) { Stop-Transcript | Out-Null }
    if ($ownsMutex) { $startupMutex.ReleaseMutex() }
    $startupMutex.Dispose()
}
