param([ValidateSet('baseline','tiny','parakeet','turbo')][string]$Model='parakeet')
$ErrorActionPreference='Stop'
$repo=Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$runtime=Join-Path $repo 'tmp\asr-comparison-20261020\manual-gateway'
$python='F:\VoiceStudio\runtime\project\.venv\Scripts\python.exe'
if (Get-NetTCPConnection -LocalPort 3902 -State Listen -ErrorAction SilentlyContinue) {
    throw 'A porta experimental 3902 ja esta ocupada.'
}
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$arguments=@(('"'+(Join-Path $PSScriptRoot 'server.py')+'"'),'--model',$Model,'--runtime',('"'+$runtime+'"'))
Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $repo -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtime 'stdout.log') -RedirectStandardError (Join-Path $runtime 'stderr.log')
Write-Output 'Comparacao iniciada em 127.0.0.1:3902. Aguarde /stt/health ficar ready. Jarvis requer o servico 3901 existente. Therion nao foi reconfigurado.'
