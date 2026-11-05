# Funcoes de prontidao sem carregar modelos ou ler configuracao pessoal.
function Read-LocalState([string]$Url) {
    $response=$null
    try {
        $request=[Net.HttpWebRequest]::Create($Url)
        $request.Proxy=$null;$request.AllowAutoRedirect=$false;$request.Timeout=3000
        try { $response=$request.GetResponse() }
        catch [Net.WebException] {
            # /health usa HTTP 503 para loading/error; o corpo e o diagnostico.
            $response=$_.Exception.Response
            if (!$response -or [int]$response.StatusCode -ne 503) { return $null }
        }
        $reader=[IO.StreamReader]::new($response.GetResponseStream())
        try { return ($reader.ReadToEnd() | ConvertFrom-Json) } finally { $reader.Dispose() }
    } catch { return $null } finally { if ($response) { $response.Close() } }
}

function Get-TherionAvailableCommit {
    if (-not ('TherionStartupMemory' -as [type])) {
        Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class TherionStartupMemory {
    [StructLayout(LayoutKind.Sequential)] public struct Status {
        public uint Length, Load;
        public ulong TotalPhysical, AvailablePhysical, TotalPageFile, AvailablePageFile;
        public ulong TotalVirtual, AvailableVirtual, AvailableExtendedVirtual;
    }
    [DllImport("kernel32.dll", SetLastError=true)]
    public static extern bool GlobalMemoryStatusEx(ref Status status);
    public static double AvailableCommitGiB() {
        Status value=new Status();value.Length=(uint)Marshal.SizeOf(typeof(Status));
        if (!GlobalMemoryStatusEx(ref value)) throw new InvalidOperationException("Memoria indisponivel");
        return value.AvailablePageFile/1073741824.0;
    }
}
'@
    }
    return [TherionStartupMemory]::AvailableCommitGiB()
}

function Get-TherionSttProfile($Config) {
    # Perfis aprovados: Parakeet no gateway 3902, ou faster-whisper dentro do Therion com Jarvis direto na 3901.
    if ($Config.tts.provider -ne 'voicestudio' -or $Config.tts.voicestudio_voice -ne '120f734a' -or
        $Config.ai.endpoint -ne 'http://127.0.0.1:11435/api/chat') { throw 'A configuracao nao corresponde a um perfil aprovado com Jarvis. Nenhuma opcao foi alterada.' }
    if ($Config.voice.provider -eq 'parakeet_http' -and $Config.voice.endpoint -eq 'http://127.0.0.1:3902/v1/audio/transcriptions' -and
        $Config.tts.voicestudio_endpoint -eq 'http://127.0.0.1:3902/v1/audio/speech') { return 'parakeet' }
    if ($Config.voice.provider -eq 'whisper' -and $Config.voice.model_path -and [IO.Directory]::Exists($Config.voice.model_path) -and
        $Config.tts.voicestudio_endpoint -eq 'http://127.0.0.1:3901/v1/audio/speech') { return 'whisper' }
    throw 'A configuracao nao corresponde ao perfil Parakeet nem ao perfil faster-whisper. Nenhuma opcao foi alterada.'
}

function Get-ParakeetStartupAction($State,[double]$AvailableCommitGiB) {
    if ($State -and $State.model -ne 'parakeet') { throw 'A porta 3902 esta ocupada por outro servico. Nenhum processo foi encerrado.' }
    if ($State.status -eq 'ready') { return 'ready' }
    if ($State.status -eq 'loading') { return 'wait' }
    if ($State.status -eq 'error' -and $State.failure_type -ne 'MemoryError') {
        throw ('Parakeet falhou ao carregar: '+$State.failure_type+'. Consulte os registros do gateway; nao houve troca de modelo.')
    }
    if ($AvailableCommitGiB -lt 2.0) {
        $available=$AvailableCommitGiB.ToString('F2',[Globalization.CultureInfo]::InvariantCulture)
        throw "Parakeet sem memoria suficiente: $available GiB de margem disponivel; sao necessarios pelo menos 2.00 GiB. Feche aplicativos pesados e abra o Therion novamente. Jarvis e o modelo de transcricao foram preservados."
    }
    if ($State.status -eq 'error') {
        return 'restart'
    }
    if ($State) { throw 'O gateway retornou um estado desconhecido. Nenhum processo foi encerrado.' }
    return 'start'
}

function Stop-FailedTherionGateway([string]$RuntimeRoot) {
    $path=Join-Path $RuntimeRoot 'gateway-process.json'
    $state=Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json
    $listener=@(Get-NetTCPConnection -LocalPort 3902 -State Listen -ErrorAction SilentlyContinue)
    if ($state.port -ne 3902 -or $listener.Count -ne 1 -or $listener[0].LocalAddress -ne '127.0.0.1' -or
        $listener[0].OwningProcess -ne $state.pid -or !$state.shutdown_token) {
        throw 'Nao confirmei a identidade do gateway com falha. Nenhum processo foi encerrado.'
    }
    $health=Read-LocalState 'http://127.0.0.1:3902/stt/health'
    if ($health.status -ne 'error' -or $health.model -ne 'parakeet' -or $health.failure_type -ne 'MemoryError') {
        throw 'O gateway nao esta mais na falha de memoria esperada. Nenhum processo foi encerrado.'
    }
    $request=[Net.HttpWebRequest]::Create('http://127.0.0.1:3902/shutdown')
    $request.Proxy=$null;$request.AllowAutoRedirect=$false;$request.Method='POST';$request.Timeout=5000
    $request.Headers['Authorization']='Bearer '+$state.shutdown_token
    $request.ContentType='application/json';$request.ContentLength=2
    $stream=$request.GetRequestStream()
    try { $stream.Write([Text.Encoding]::UTF8.GetBytes('{}'),0,2) } finally { $stream.Dispose() }
    $response=$request.GetResponse();$response.Close()
    $timer=[Diagnostics.Stopwatch]::StartNew()
    while (Get-NetTCPConnection -LocalPort 3902 -State Listen -ErrorAction SilentlyContinue) {
        if ($timer.Elapsed.TotalSeconds -gt 8) { throw 'O gateway com falha nao encerrou. Nao iniciei outra copia.' }
        Start-Sleep -Milliseconds 200
    }
}
