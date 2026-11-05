param([switch]$Force)
$ErrorActionPreference = 'Stop'
$minimalProjectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$minimalStatePath = Join-Path $minimalProjectRoot 'tmp\omnivoice-minimal-20261020\process.json'
if (!(Test-Path -LiteralPath $minimalStatePath)) { throw 'Nenhum estado de backend mínimo encontrado.' }
$minimalState = Get-Content -LiteralPath $minimalStatePath -Raw | ConvertFrom-Json
if ($minimalState.port -lt 1 -or $minimalState.port -gt 65535) { throw 'Porta inválida no estado.' }
if ($Force) {
    $minimalProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($minimalState.pid)"
    $minimalServerScript = Join-Path $PSScriptRoot 'server.py'
    if (!$minimalProcessInfo -or !$minimalProcessInfo.CommandLine.Contains($minimalServerScript) -or !$minimalProcessInfo.CommandLine.Contains((Split-Path $minimalStatePath -Parent))) {
        throw 'Identidade do processo não confirmada; nada foi encerrado.'
    }
    $minimalParentInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $($minimalProcessInfo.ParentProcessId)"
    Stop-Process -Id $minimalProcessInfo.ProcessId
    if ($minimalParentInfo -and $minimalParentInfo.CommandLine.Contains($minimalServerScript)) {
        Stop-Process -Id $minimalParentInfo.ProcessId -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $minimalStatePath
    Write-Output 'Somente o processo do backend mínimo de teste foi encerrado.'
    return
}
$minimalStopHeaders = @{ Authorization = ('Bearer ' + $minimalState.shutdown_token) }
Invoke-RestMethod -Uri "http://127.0.0.1:$($minimalState.port)/shutdown" -Method Post -Headers $minimalStopHeaders -TimeoutSec 10
$minimalStoppingProcess = Get-Process -Id $minimalState.pid -ErrorAction SilentlyContinue
if ($minimalStoppingProcess -and !$minimalStoppingProcess.WaitForExit(30000)) {
    throw 'Encerramento solicitado, mas o processo ainda não terminou após 30 segundos.'
}
