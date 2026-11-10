# Liga (ou desfaz, com -Desfazer) o modo estação no tablet pelo ADB: app como tela inicial, sem bloqueio,
# sem a barra do Android e com a animação de inicialização do Therion.
param(
    [string]$UrlPorteiro,
    [switch]$Desfazer
)
$ErrorActionPreference = 'Stop'

$adbExe = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Microsoft\WinGet\Packages') -Directory -Filter 'Genymobile.scrcpy_*' -ErrorAction SilentlyContinue |
    ForEach-Object { Get-ChildItem $_.FullName -Recurse -Filter 'adb.exe' -ErrorAction SilentlyContinue } |
    Select-Object -First 1
if (-not $adbExe) { throw 'adb.exe do scrcpy não encontrado (instale o scrcpy pelo winget).' }
$adb = $adbExe.FullName
$env:ADB_LIBUSB = '1'
$dados = Join-Path $env:LOCALAPPDATA 'Therion\estacao'
$banco = '/data/data/com.android.providers.settings/databases/settings.db'
$fabrica = Join-Path $dados 'bootanimation-fabrica.zip'

function Adb([string[]]$argumentos) {
    # O adb escreve progresso no stderr; com 'Stop' o PowerShell 5.1 trataria isso como erro fatal.
    $ErrorActionPreference = 'Continue'
    $saida = (& $adb @argumentos 2>&1 | ForEach-Object { "$_" } | Out-String).Trim()
    if ($LASTEXITCODE -ne 0) { throw "adb $($argumentos -join ' '): $saida" }
    return $saida
}

# O PowerShell 5.1 perde aspas internas ao chamar programas; \" chega ao adb como aspas de verdade.
function Sql([string]$consulta) { return Adb @('shell', ('sqlite3 ' + $banco + ' \"' + $consulta + '\"')) }

function Passo([string]$nome, [scriptblock]$acao, [string]$esperado) {
    try {
        $saida = & $acao
        if ($esperado -and ($saida -notmatch [regex]::Escape($esperado))) { throw $saida }
        Write-Output "[ok] $nome"
    } catch {
        Write-Output "[falhou] ${nome}: $($_.Exception.Message)"
        exit 1
    }
}

if ((& $adb get-state 2>&1 | Out-String).Trim() -ne 'device') {
    throw 'O tablet não está conectado no ADB (cabo, depuração USB ligada).'
}
if ((Adb @('shell', 'su -c id')) -notmatch 'uid=0') { throw 'FALHOU: su não responde' }

if ($Desfazer) {
    Passo 'ligar a barra do Android' { Adb @('shell', 'pm enable com.android.systemui') } 'enabled'
    Passo 'ligar o launcher de fábrica' { Adb @('shell', 'pm enable com.android.launcher') } 'enabled'
    Passo 'religar a tela de bloqueio' { Sql "insert or replace into secure(name,value) values('lockscreen.disabled','0');" }
    Passo 'voltar a animação de fábrica' {
        Adb @('shell', 'rm -f /data/local/bootanimation.zip') | Out-Null
        if (Test-Path -LiteralPath $fabrica) {
            Adb @('push', $fabrica, '/data/local/tmp/fabrica.zip') | Out-Null
            Adb @('shell', "su -c 'mount -o remount,rw /system && cat /data/local/tmp/fabrica.zip > /system/media/bootanimation.zip; chmod 644 /system/media/bootanimation.zip; mount -o remount,ro /system; rm /data/local/tmp/fabrica.zip'")
        }
    }
    Passo 'desinstalar o app Estação' { Adb @('shell', 'pm uninstall com.therion.estacao') } 'Success'
    Passo 'reiniciar o tablet' { Adb @('reboot') }
    return
}

if (-not $UrlPorteiro) { throw 'Informe -UrlPorteiro http://<IP do PC>:3904/' }
$apk = Join-Path $dados 'estacao.apk'
$boot = Join-Path $dados 'bootanimation.zip'
foreach ($arquivo in $apk, $boot) {
    if (-not (Test-Path -LiteralPath $arquivo)) { throw "Falta $arquivo (rode app\build.ps1 e tablet\bootanimacao.py)." }
}

Passo 'instalar o app Estação' { Adb @('install', '-r', $apk) } 'Success'
Passo 'gravar o endereço do porteiro' {
    Adb @('shell', 'am force-stop com.therion.estacao') | Out-Null
    Adb @('shell', "am start -n com.therion.estacao/.EstacaoActivity --es url $UrlPorteiro")
} 'Starting'
Passo 'desativar o launcher de fábrica' { Adb @('shell', 'pm disable com.android.launcher') } 'disabled'
Passo 'desligar a tela de bloqueio' {
    $tipo = Sql "select value from secure where name='lockscreen.password_type';"
    if ($tipo -and $tipo -ne '65536') { throw 'o tablet tem PIN, senha ou padrão; tire em Configurações > Segurança primeiro' }
    Sql "insert or replace into secure(name,value) values('lockscreen.disabled','1');"
}
Passo 'copiar a animação de inicialização' {
    # Este tablet monta /data tarde: a primeira animação vem de /system. Troca as duas e guarda a de fábrica.
    if (-not (Test-Path -LiteralPath $fabrica)) { Adb @('pull', '/system/media/bootanimation.zip', $fabrica) | Out-Null }
    Adb @('push', $boot, '/data/local/bootanimation.zip') | Out-Null
    Adb @('shell', 'chmod 644 /data/local/bootanimation.zip') | Out-Null
    Adb @('shell', "su -c 'mount -o remount,rw /system && cat /data/local/bootanimation.zip > /system/media/bootanimation.zip; chmod 644 /system/media/bootanimation.zip; mount -o remount,ro /system'")
}
Passo 'desligar a barra do Android' { Adb @('shell', 'pm disable com.android.systemui') } 'disabled'
Passo 'reiniciar o tablet' { Adb @('reboot') }
