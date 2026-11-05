$ErrorActionPreference='Stop'
$repo=Split-Path $PSScriptRoot -Parent
$state=Join-Path $env:LOCALAPPDATA 'Therion\voice'
& (Join-Path $repo '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'voice_gateway\install_assets.py')
if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel publicar os arquivos da voz.' }
$shell=New-Object -ComObject WScript.Shell
$powershell=Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$launcher=Join-Path $PSScriptRoot 'Start-Therion.ps1'
$entries=@(
    @{path=(Join-Path ([Environment]::GetFolderPath('Desktop')) 'Therion.lnk');backup='desktop.lnk';minimized=$false},
    @{path=(Join-Path ([Environment]::GetFolderPath('Startup')) 'Therion V4.lnk');backup='startup.lnk';minimized=$true}
)
$records=@()
foreach ($entry in $entries) {
    # Atualizar somente atalhos que ja existem e apontam a este projeto.
    if (!(Test-Path -LiteralPath $entry.path)) { continue }
    $old=$shell.CreateShortcut($entry.path)
    $python=Join-Path $repo '.venv\Scripts\pythonw.exe'
    if ($old.TargetPath -ne $python -and !($old.TargetPath -eq $powershell -and $old.Arguments.Contains($launcher))) {
        throw ('Destino inesperado; atalho preservado: '+$entry.path)
    }
    $backup=Join-Path (Join-Path $state 'rollback') $entry.backup
    if (!(Test-Path -LiteralPath $backup)) { Copy-Item -LiteralPath $entry.path -Destination $backup }
    $temporary=$entry.path+'.new.lnk'
    $shortcut=$shell.CreateShortcut($temporary)
    $shortcut.TargetPath=$powershell
    $shortcut.Arguments='-NoProfile -ExecutionPolicy Bypass '
    if ($entry.minimized) { $shortcut.Arguments+='-WindowStyle Hidden ' }
    $shortcut.Arguments+='-File "'+$launcher+'"'
    if ($entry.minimized) { $shortcut.Arguments+=' -StartMinimized -Quiet' }
    $shortcut.WorkingDirectory=$repo
    $shortcut.IconLocation=$old.IconLocation
    $shortcut.Description='Therion — Parakeet e Jarvis'
    $shortcut.Save()
    Move-Item -LiteralPath $temporary -Destination $entry.path -Force
    $verified=$shell.CreateShortcut($entry.path)
    if ($verified.TargetPath -ne $powershell -or !$verified.Arguments.Contains($launcher)) { throw 'Atalho nao confirmado apos gravacao.' }
    $records+=@{path=$entry.path;backup=$entry.backup;backup_sha256=(Get-FileHash -LiteralPath $backup).Hash}
}
@{status='adopted';shortcuts=$records;configuration_changed=$false;utc=[DateTime]::UtcNow.ToString('o')} | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $state 'adoption-result.json') -Encoding UTF8
Write-Output 'Atalhos normais integrados ao perfil aprovado. Nenhum autostart novo foi criado.'
