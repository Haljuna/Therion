$ErrorActionPreference='Stop'
$repo=Split-Path $PSScriptRoot -Parent
if (Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'pythonw.exe' -and $_.CommandLine -like ('*'+$repo+'*') -and $_.CommandLine -like '*-m therion.interface.desktop*' }) { throw 'Use Sair no Therion antes de restaurar a configuracao.' }
$state=Join-Path $env:LOCALAPPDATA 'Therion\voice'
$rollback=Join-Path $state 'rollback'
$receipt=Get-Content -LiteralPath (Join-Path $state 'adoption-result.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$allowed=@((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Therion.lnk'),(Join-Path ([Environment]::GetFolderPath('Startup')) 'Therion V4.lnk'))
$shell=New-Object -ComObject WScript.Shell
foreach ($entry in $receipt.shortcuts) {
    if ($entry.path -notin $allowed -or $entry.backup -notin @('desktop.lnk','startup.lnk')) { throw 'Destino de reversao inesperado.' }
    $backup=Join-Path $rollback $entry.backup
    if ((Get-FileHash -LiteralPath $backup).Hash -ne $entry.backup_sha256) { throw 'Backup do atalho mudou.' }
    $current=$shell.CreateShortcut($entry.path)
    if (!$current.Arguments.Contains((Join-Path $PSScriptRoot 'Start-Therion.ps1'))) { throw 'Atalho foi alterado depois da adocao; reversao bloqueada.' }
}
& (Join-Path $repo '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'voice_gateway\switch_therion.py') restore --runtime $rollback
if ($LASTEXITCODE -ne 0) { throw 'Configuracao nao foi revertida; atalhos preservados.' }
foreach ($entry in $receipt.shortcuts) { Copy-Item -LiteralPath (Join-Path $rollback $entry.backup) -Destination $entry.path -Force }
Write-Output 'Campos da voz e atalhos anteriores restaurados. Reabra o Therion para carregar.'
