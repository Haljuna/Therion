# Registra (ou remove, com -Remover) a tarefa agendada que mantém o porteiro da Estação Therion ligado.
param([switch]$Remover)
$ErrorActionPreference = 'Stop'
$nome = 'Therion Estacao'

if ($Remover) {
    Unregister-ScheduledTask -TaskName $nome -Confirm:$false -ErrorAction SilentlyContinue
    Write-Output "Tarefa '$nome' removida."
    return
}

$config = Join-Path $env:LOCALAPPDATA 'Therion\estacao\config.json'
if (-not (Test-Path -LiteralPath $config -PathType Leaf)) {
    throw "Crie primeiro $config (veja o README da pasta scripts\estacao)."
}

$repo = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$python = Join-Path $repo '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python do Therion não encontrado em $python."
}

$acao = New-ScheduledTaskAction -Execute $python -Argument 'scripts\estacao\porteiro.py' -WorkingDirectory $repo
$gatilho = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$ajustes = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $nome -Action $acao -Trigger $gatilho -Settings $ajustes -Force | Out-Null
Start-ScheduledTask -TaskName $nome
Write-Output "Tarefa '$nome' registrada e iniciada (porteiro em $repo)."
