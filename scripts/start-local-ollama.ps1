# Inicialização da instância local adotada nesta instalação do Thérion.
$ErrorActionPreference = 'Stop'
$taskClient = [Net.Sockets.TcpClient]::new()
try {
    $taskConnection = $taskClient.ConnectAsync('127.0.0.1', 11435)
    if ($taskConnection.Wait(1000) -and $taskClient.Connected) { return }
} catch {
    # Ausência do serviço é esperada antes de iniciar.
} finally {
    $taskClient.Dispose()
}
# Instalação em F: (o disco C: não tem espaço para as bibliotecas CUDA); a padrão fica como alternativa.
$taskExecutable = 'F:\Ollama\ollama.exe'
if (-not (Test-Path -LiteralPath $taskExecutable -PathType Leaf)) {
    $taskExecutable = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama.exe'
}
$taskModels = 'F:\Therion\ollama-models'
if (-not (Test-Path -LiteralPath $taskExecutable -PathType Leaf)) {
    throw 'Executável do Ollama não encontrado.'
}
if (-not (Test-Path -LiteralPath $taskModels -PathType Container)) {
    throw 'Diretório dos modelos do Thérion não encontrado.'
}
$env:OLLAMA_HOST = '127.0.0.1:11435'
$env:OLLAMA_MODELS = $taskModels
Start-Process -FilePath $taskExecutable -ArgumentList 'serve' -WindowStyle Hidden
