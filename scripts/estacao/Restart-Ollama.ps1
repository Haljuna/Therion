# Reinicia só o Ollama do Therion (porta 11435). Usado pelo botão 3 da Estação Therion.
$ErrorActionPreference = 'Stop'
$conexao = Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($conexao) {
    $processo = Get-Process -Id $conexao.OwningProcess -ErrorAction Stop
    if ($processo.ProcessName -ne 'ollama') {
        throw 'A porta 11435 não é do Ollama; nada foi encerrado.'
    }
    Stop-Process -Id $processo.Id -Force
    $limite = (Get-Date).AddSeconds(15)
    while ((Get-NetTCPConnection -LocalPort 11435 -State Listen -ErrorAction SilentlyContinue) -and (Get-Date) -lt $limite) {
        Start-Sleep -Milliseconds 300
    }
}
& (Join-Path $PSScriptRoot '..\start-local-ollama.ps1')
