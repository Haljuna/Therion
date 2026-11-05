param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$voiceTestRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$voiceTestRuntime = Join-Path $voiceTestRoot 'tmp\omnivoice-minimal-20261020'
$voiceTestConfigPath = Join-Path $env:APPDATA 'Therion\config.json'
$voiceTestConfig = Get-Content -LiteralPath $voiceTestConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($voiceTestConfig.tts.voicestudio_endpoint -ne 'http://127.0.0.1:3901/v1/audio/speech' -or
    $voiceTestConfig.tts.voicestudio_voice -ne '120f734a' -or
    $voiceTestConfig.ai.endpoint -ne 'http://127.0.0.1:11435/api/chat') {
    throw 'A configuracao nao corresponde ao teste Jarvis. Nenhuma opcao foi alterada.'
}

function Get-VoiceTestJson([string]$Url) {
    $voiceTestResponse = $null
    try {
        $voiceTestRequest = [Net.HttpWebRequest]::Create($Url)
        $voiceTestRequest.Proxy = $null
        $voiceTestRequest.Timeout = 4000
        $voiceTestRequest.KeepAlive = $false
        $voiceTestResponse = $voiceTestRequest.GetResponse()
        $voiceTestReader = [IO.StreamReader]::new($voiceTestResponse.GetResponseStream())
        try { return ($voiceTestReader.ReadToEnd() | ConvertFrom-Json) }
        finally { $voiceTestReader.Dispose() }
    } catch { return $null }
    finally { if ($voiceTestResponse) { $voiceTestResponse.Close() } }
}

function Send-VoiceTestRequest([string]$Url, [object]$Payload, [int]$TimeoutSeconds) {
    $voiceTestPayloadBytes = [Text.Encoding]::UTF8.GetBytes(($Payload | ConvertTo-Json -Depth 8 -Compress))
    $voiceTestRequest = [Net.HttpWebRequest]::Create($Url)
    $voiceTestRequest.Proxy = $null
    $voiceTestRequest.Method = 'POST'
    $voiceTestRequest.ContentType = 'application/json'
    $voiceTestRequest.ContentLength = $voiceTestPayloadBytes.Length
    $voiceTestRequest.Timeout = $TimeoutSeconds * 1000
    $voiceTestRequest.ReadWriteTimeout = $TimeoutSeconds * 1000
    $voiceTestRequest.KeepAlive = $false
    $voiceTestStream = $voiceTestRequest.GetRequestStream()
    try { $voiceTestStream.Write($voiceTestPayloadBytes, 0, $voiceTestPayloadBytes.Length) }
    finally { $voiceTestStream.Dispose() }
    # Nunca repetir POST apos timeout ou erro de geracao.
    $voiceTestResponse = $voiceTestRequest.GetResponse()
    try {
        $voiceTestOutput = [IO.MemoryStream]::new()
        try {
            $voiceTestResponse.GetResponseStream().CopyTo($voiceTestOutput)
            return ,($voiceTestOutput.ToArray())
        } finally { $voiceTestOutput.Dispose() }
    } finally { $voiceTestResponse.Close() }
}

$voiceTestState = Get-VoiceTestJson 'http://127.0.0.1:3901/startup/progress'
$voiceTestOllamaState = Get-VoiceTestJson 'http://127.0.0.1:11435/api/version'
if ($CheckOnly) {
    [pscustomobject]@{ voice = $(if ($voiceTestState) {$voiceTestState.status} else {'offline'});
        ollama = [bool]$voiceTestOllamaState; model = $voiceTestConfig.ai.model;
        changed_configuration = $false } | ConvertTo-Json -Compress
    return
}

Write-Output 'Preparando o teste local Jarvis. A primeira carga pode levar alguns minutos.'
if (!$voiceTestState) {
    if (Get-NetTCPConnection -LocalPort 3901 -State Listen -ErrorAction SilentlyContinue) {
        throw 'A porta da voz esta ocupada e nao confirmou o servico esperado. Nada foi encerrado.'
    }
    & (Join-Path $PSScriptRoot 'Start-VoiceMinimal.ps1')
}
$voiceTestTimer = [Diagnostics.Stopwatch]::StartNew()
$voiceTestLastPhase = ''
do {
    $voiceTestState = Get-VoiceTestJson 'http://127.0.0.1:3901/startup/progress'
    if ($voiceTestState -and $voiceTestState.status -eq 'error') {
        throw "Falha na voz: $($voiceTestState.phase), $($voiceTestState.failure_type). Nao houve troca de modelo."
    }
    if ($voiceTestState -and $voiceTestState.phase -ne $voiceTestLastPhase) {
        $voiceTestLastPhase = $voiceTestState.phase
        Write-Output "Voz: $voiceTestLastPhase"
    }
    if ($voiceTestState -and $voiceTestState.status -eq 'ready') { break }
    Start-Sleep -Seconds 3
} while ($voiceTestTimer.Elapsed.TotalSeconds -lt 300)
if (!$voiceTestState -or $voiceTestState.status -ne 'ready') {
    throw 'A voz ainda nao esta pronta apos cinco minutos. Consulte os logs do teste.'
}

Write-Output 'Iniciando a instancia local do Ollama...'
& (Join-Path $voiceTestRoot 'scripts\start-local-ollama.ps1')
$voiceTestTimer.Restart()
do {
    $voiceTestOllamaState = Get-VoiceTestJson 'http://127.0.0.1:11435/api/version'
    if ($voiceTestOllamaState) { break }
    Start-Sleep -Seconds 2
} while ($voiceTestTimer.Elapsed.TotalSeconds -lt 90)
if (!$voiceTestOllamaState) { throw 'O Ollama nao confirmou prontidao. Nao foi iniciado outro modelo.' }

Write-Output 'Carregando a mesma IA configurada. Aguarde antes de conversar...'
$voiceTestWarmPayload = @{
    model = $voiceTestConfig.ai.model
    messages = @(@{ role = 'user'; content = 'Responda somente OK.' })
    stream = $false; think = $false; keep_alive = '30m'
    options = @{num_ctx = 8192; num_predict = 8}
}
$voiceTestWarmBytes = Send-VoiceTestRequest $voiceTestConfig.ai.endpoint $voiceTestWarmPayload 240
$voiceTestWarmResult = [Text.Encoding]::UTF8.GetString($voiceTestWarmBytes) | ConvertFrom-Json
if (!$voiceTestWarmResult.done -or !$voiceTestWarmResult.message.content) {
    throw 'A IA nao concluiu o teste de prontidao.'
}

Write-Output 'Aquecendo a voz sem reproduzir audio...'
$voiceTestWarmAudio = Send-VoiceTestRequest $voiceTestConfig.tts.voicestudio_endpoint @{
    model='tts-1'; voice='120f734a'; input='Ola.'; language='pt'; response_format='wav'
} 90
if ($voiceTestWarmAudio.Length -lt 44 -or [Text.Encoding]::ASCII.GetString($voiceTestWarmAudio,0,4) -ne 'RIFF' -or
    [Text.Encoding]::ASCII.GetString($voiceTestWarmAudio,8,4) -ne 'WAVE') {
    throw 'A voz nao retornou um WAV valido. O texto da configuracao nao foi alterado.'
}
New-Item -ItemType Directory -Path $voiceTestRuntime -Force | Out-Null
[pscustomobject]@{ utc=[DateTime]::UtcNow.ToString('o'); voice_ready=$true; ai_ready=$true;
    model=$voiceTestConfig.ai.model; silent_warmup=$true; changed_configuration=$false } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $voiceTestRuntime 'manual-launch-result.json') -Encoding UTF8

Write-Output 'Servicos prontos. Abrindo o Therion; se ja estiver aberto, use a janela existente.'
Start-Process -FilePath (Join-Path $voiceTestRoot '.venv\Scripts\pythonw.exe') -ArgumentList @('-m','therion.interface.desktop') -WorkingDirectory $voiceTestRoot -WindowStyle Hidden
