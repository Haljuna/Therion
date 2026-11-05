param(
    [int]$Port = 3901,
    [ValidateSet(8,16)][int]$Steps = 16,
    [string]$VoiceStudioRoot = 'F:\VoiceStudio',
    [string]$RuntimeRoot = ''
)
$ErrorActionPreference = 'Stop'
$minimalProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$minimalRuntimeRoot = Join-Path $minimalProjectRoot 'tmp\omnivoice-minimal-20261020'
if ($RuntimeRoot) { $minimalRuntimeRoot = [IO.Path]::GetFullPath($RuntimeRoot) }
$minimalPythonPath = Join-Path $VoiceStudioRoot 'runtime\project\.venv\Scripts\python.exe'
$minimalSourceRoot = Join-Path $VoiceStudioRoot 'runtime\project'
$minimalCheckpoint = Join-Path $VoiceStudioRoot 'models\models--k2-fsa--OmniVoice\snapshots\c5fdb5ccb189668d56333f77ba2629f4cd7535f4'
if (!(Test-Path -LiteralPath $minimalPythonPath) -or !(Test-Path -LiteralPath (Join-Path $minimalCheckpoint 'model.safetensors'))) {
    throw 'Runtime/pesos instalados não encontrados. Nada será baixado.'
}
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) {
    throw "A porta $Port já está em uso; nenhum processo foi encerrado."
}
$minimalSystemInfo = Get-CimInstance Win32_OperatingSystem
if ($minimalSystemInfo.FreePhysicalMemory -lt 4MB -or $minimalSystemInfo.FreeVirtualMemory -lt 6MB) {
    throw 'O teste isolado precisa de pelo menos 4 GiB de RAM e 6 GiB de margem virtual livres.'
}
New-Item -ItemType Directory -Path $minimalRuntimeRoot -Force | Out-Null
$minimalProfilePath = Join-Path $minimalRuntimeRoot 'profile.json'
if (!(Test-Path -LiteralPath $minimalProfilePath)) {
    & $minimalPythonPath (Join-Path $PSScriptRoot 'prepare_profile.py') --data-root (Join-Path $VoiceStudioRoot 'data') --profile-id '120f734a' --output $minimalProfilePath
    if ($LASTEXITCODE -ne 0) { throw 'Não foi possível preparar o perfil salvo.' }
}
$env:HF_HOME = Join-Path $VoiceStudioRoot 'models'
$env:HF_HUB_OFFLINE = '1'
$env:TRANSFORMERS_OFFLINE = '1'
$env:TEMP = Join-Path $VoiceStudioRoot 'temp'
$env:TMP = Join-Path $VoiceStudioRoot 'temp'
$minimalArguments = @(
    ('"' + (Join-Path $PSScriptRoot 'server.py') + '"'),
    '--profile', ('"' + $minimalProfilePath + '"'),
    '--runtime', ('"' + $minimalRuntimeRoot + '"'),
    '--source-root', ('"' + $minimalSourceRoot + '"'),
    '--checkpoint', ('"' + $minimalCheckpoint + '"'),
    '--port', $Port, '--steps', $Steps
)
$minimalProcess = Start-Process -FilePath $minimalPythonPath -ArgumentList $minimalArguments -WorkingDirectory $minimalSourceRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $minimalRuntimeRoot 'server-out.log') -RedirectStandardError (Join-Path $minimalRuntimeRoot 'server-error.log')
Write-Output "Backend mínimo iniciado: processo $($minimalProcess.Id), porta $Port. Prontidão: http://127.0.0.1:$Port/health"
