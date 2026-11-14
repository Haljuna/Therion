# Monta o app "Estação" (APK para Android 4.0) sem Gradle. Saída: %LOCALAPPDATA%\Therion\estacao\estacao.apk
param([string]$Sdk = 'F:\Android-SDK')
$ErrorActionPreference = 'Stop'

$buildTools = Join-Path $Sdk 'build-tools\35.0.0'
$androidJar = Join-Path $Sdk 'platforms\android-15\android.jar'
$faltando = @()
if (-not (Test-Path (Join-Path $Sdk 'cmdline-tools\latest'))) { $faltando += 'cmdline-tools/latest' }
if (-not (Test-Path (Join-Path $buildTools 'aapt2.exe'))) { $faltando += 'build-tools;35.0.0' }
if (-not (Test-Path $androidJar)) { $faltando += 'platforms;android-15' }
if ($faltando) { throw "Falta no SDK ($Sdk): $($faltando -join ', ')" }

$jdk = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Programs\Eclipse Adoptium') -Directory -Filter 'jdk-21*' -ErrorAction SilentlyContinue |
    Select-Object -First 1
if (-not $jdk) { throw 'JDK 21 (Eclipse Adoptium) não encontrado.' }
$env:JAVA_HOME = $jdk.FullName
$env:PATH = (Join-Path $jdk.FullName 'bin') + ';' + $env:PATH

$app = $PSScriptRoot
$saida = Join-Path $env:LOCALAPPDATA 'Therion\estacao'
$obra = Join-Path $saida 'build'
if (Test-Path $obra) { Remove-Item -Recurse -Force $obra }
New-Item -ItemType Directory -Force (Join-Path $obra 'classes'), (Join-Path $obra 'dex') | Out-Null

function Rodar([string]$exe, [string[]]$argumentos) {
    & $exe @argumentos
    if ($LASTEXITCODE -ne 0) { throw "Falhou: $exe $($argumentos -join ' ')" }
}

$base = Join-Path $obra 'base.apk'
Rodar (Join-Path $buildTools 'aapt2.exe') @('link', '-o', $base, '--manifest', (Join-Path $app 'AndroidManifest.xml'),
    '-I', $androidJar, '-A', (Join-Path $app 'assets'), '--min-sdk-version', '15', '--target-sdk-version', '15')

$fontes = Get-ChildItem (Join-Path $app 'src') -Recurse -Filter '*.java' | ForEach-Object FullName
Rodar 'javac' (@('--release', '8', '-Xlint:-options', '-encoding', 'UTF-8', '-classpath', $androidJar, '-d', (Join-Path $obra 'classes')) + $fontes)

$classes = Get-ChildItem (Join-Path $obra 'classes') -Recurse -Filter '*.class' | ForEach-Object FullName
Rodar (Join-Path $buildTools 'd8.bat') (@('--min-api', '15', '--lib', $androidJar, '--output', (Join-Path $obra 'dex')) + $classes)

Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [IO.Compression.ZipFile]::Open($base, 'Update')
try { [void][IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, (Join-Path $obra 'dex\classes.dex'), 'classes.dex') }
finally { $zip.Dispose() }

$alinhado = Join-Path $obra 'alinhado.apk'
Rodar (Join-Path $buildTools 'zipalign.exe') @('-f', '-p', '4', $base, $alinhado)

$chave = Join-Path $saida 'estacao.keystore'
$senhaArquivo = Join-Path $saida 'estacao.keystore.senha'
if (-not (Test-Path $chave)) {
    $bytes = New-Object byte[] 24
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $senha = [Convert]::ToBase64String($bytes)
    Set-Content -LiteralPath $senhaArquivo -Value $senha -Encoding ASCII -NoNewline
    Rodar 'keytool' @('-genkeypair', '-keystore', $chave, '-storepass', $senha, '-keypass', $senha, '-alias', 'estacao',
        '-keyalg', 'RSA', '-keysize', '2048', '-validity', '10000', '-dname', 'CN=Estacao Therion')
}
$senha = Get-Content -LiteralPath $senhaArquivo -Raw
$apk = Join-Path $saida 'estacao.apk'
Rodar (Join-Path $buildTools 'apksigner.bat') @('sign', '--ks', $chave, '--ks-pass', "pass:$senha", '--ks-key-alias', 'estacao',
    '--min-sdk-version', '15', '--out', $apk, $alinhado)
Write-Output "APK pronto: $apk"
