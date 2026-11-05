param(
    [ValidateSet('App','Ollama')][string]$Mode='App',
    [switch]$StartMinimized,
    [switch]$Quiet,
    [switch]$CheckOnly
)
$ErrorActionPreference='Stop'

function Resolve-TherionInstallation([string]$Root,[string]$SelectedMode='App') {
    $entry=if($SelectedMode -eq 'Ollama'){'scripts\start-local-ollama.ps1'}else{'scripts\Start-Therion.ps1'}
    if (![IO.File]::Exists([IO.Path]::Combine($Root,$entry)) -or
        ![IO.File]::Exists([IO.Path]::Combine($Root,'.venv\Scripts\pythonw.exe'))) {
        throw 'Therion indisponivel: conecte o disco F: e confira F:\Therion\app. Nenhuma instalacao antiga foi iniciada.'
    }
    return [IO.Path]::Combine($Root,$entry)
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        $root='F:\Therion\app'
        $entry=Resolve-TherionInstallation $root $Mode
        if ($CheckOnly) {
            Write-Output "Instalacao localizada em $root; nenhum servico foi iniciado."
            exit 0
        }
        Push-Location -LiteralPath $root
        try {
            if ($Mode -eq 'Ollama') { & $entry }
            else { & $entry -StartMinimized:$StartMinimized -Quiet:$Quiet }
        } finally { Pop-Location }
    } catch {
        $message=$_.Exception.Message
        $errorFile=Join-Path $env:LOCALAPPDATA 'Therion\launch-error.txt'
        try { [IO.File]::WriteAllText($errorFile,$message,[Text.UTF8Encoding]::new($false)) } catch {}
        if (!$Quiet) {
            Add-Type -AssemblyName PresentationFramework
            [System.Windows.MessageBox]::Show($message,'Therion') | Out-Null
        }
        Write-Error -Message $message -ErrorAction Continue
        exit 1
    }
}
